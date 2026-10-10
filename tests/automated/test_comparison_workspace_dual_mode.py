"""Startup contracts: synthetic data/credentials, SDK double, external sockets blocked."""
import hashlib
import io
import os
from pathlib import Path
import runpy
import socket
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app import comparison_workspace_main as entry
from tests.automated.test_comparison_workspace_live_ai import KEYS, MODELS, wait_run
from tests.fixtures.comparison_workspace.mock_live_sdk import MockRawResponse, response_for

ROOT = Path(__file__).resolve().parents[2]


class DualModeTests(unittest.TestCase):
    def setUp(self):
        system = {name: os.environ[name] for name in
                  ("PROCESSOR_ARCHITECTURE", "PROCESSOR_ARCHITEW6432", "SYSTEMROOT", "WINDIR") if name in os.environ}
        clean = patch.dict(os.environ, system, clear=True)
        clean.start(); self.addCleanup(clean.stop)
        for name in ("connect", "connect_ex"):
            original = getattr(socket.socket,name)
            def loopback_only(sock,address,*args,original=original):
                # Windows asyncio creates a loopback socketpair even for in-process TestClient.
                if isinstance(address,tuple) and address[0] in {"127.0.0.1","::1"}:
                    return original(sock,address,*args)
                raise AssertionError("External sockets forbidden")
            guard = patch("socket.socket."+name,new=loopback_only)
            guard.start(); self.addCleanup(guard.stop)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.sdk = Mock()
        self.sdk.responses.create.side_effect = response_for
        self.sdk.responses.with_raw_response.parse.side_effect = lambda **kw: MockRawResponse(response_for(**kw))
        constructor = patch("openai.OpenAI", return_value=self.sdk)
        self.constructor = constructor.start(); self.addCleanup(constructor.stop)

    def app(self, data, offline):
        os.environ["DISABLE_LIVE_API"] = "true" if offline else "false"
        # Declared empty static index avoids any installation/build/network in this CLI contract test.
        index = self.root / "web/comparison-workspace/dist/index.html"
        index.parent.mkdir(parents=True, exist_ok=True); index.write_text("offline test", encoding="utf-8")
        with patch.object(entry, "__file__", str(self.root/"app/comparison_workspace_main.py")), \
                patch("uvicorn.run") as serve, redirect_stdout(io.StringIO()):
            entry.main(["--data-dir", str(data), "--port", "8765", "--enable-api"])
        serve.assert_called_once()
        self.assertEqual(serve.call_args.kwargs["host"], "127.0.0.1")
        return serve.call_args.args[0]

    def test_offline_launcher_strips_inherited_credentials_and_hands_off_same_directory(self):
        script = self.root / "scripts/start_comparison_workspace.py"
        script.parent.mkdir(); script.write_bytes((ROOT/"scripts/start_comparison_workspace.py").read_bytes())
        python = self.root / (".venv-workspace/Scripts/python.exe" if os.name == "nt" else ".venv-workspace/bin/python")
        python.parent.mkdir(parents=True); python.touch()
        module = runpy.run_path(str(script))
        target = self.root / "shared data"
        inherited = {"DISABLE_LIVE_API": "false", **{name.upper()+"_API_KEY": key for name,key in KEYS.items()},
                     **{"COMPARISON_"+name.upper()+"_MODEL": value for name,value in MODELS.items()}}
        with patch.dict(os.environ, inherited), patch("sys.argv", [str(script), "--data-dir", str(target)]), \
                patch("shutil.which", side_effect=lambda name:name), patch("subprocess.check_output", return_value="v22.21.0"), \
                patch("subprocess.run") as launch, patch("venv.EnvBuilder") as builder, redirect_stdout(io.StringIO()):
            module["main"]()
        builder.assert_not_called(); launch.assert_called_once()
        args = launch.call_args.args[0]
        self.assertEqual(args[:3], [str(python), "-m", "app.comparison_workspace_main"])
        self.assertEqual(args[-2:], ["--data-dir", str(target.resolve())])
        env = launch.call_args.kwargs["env"]
        self.assertEqual(env["DISABLE_LIVE_API"], "true")
        for provider,key in KEYS.items():
            self.assertNotIn(provider.upper()+"_API_KEY", env)
            self.assertNotIn("COMPARISON_"+provider.upper()+"_MODEL", env)
            self.assertNotIn(key, str(args))
        self.constructor.assert_not_called()

    def test_normal_hard_offline_and_restart_share_projects_but_never_restore_session_authorization(self):
        data = self.root / "shared data"
        first = self.app(data, offline=False)
        with TestClient(first, base_url="http://127.0.0.1") as client:
            initial = client.get("/api/capabilities").json()
            self.assertFalse(initial["hard_offline"])
            self.assertFalse(initial["live_enabled"])  # --enable-api is not authorization.
            workspace = first.state.workspace
            project,demo = workspace.seed_demo(); wait_run(workspace,demo.id)
            for provider in KEYS:
                saved = client.patch("/api/ai-settings", json={"provider":provider,"api_key":KEYS[provider],"model":MODELS[provider]})
                self.assertEqual(saved.status_code,200)
                self.assertFalse(saved.json()["api_enabled"])
                self.assertEqual(client.patch("/api/ai-settings",json={"provider":provider,"live_enabled":True}).status_code,422)
                self.assertEqual(client.patch("/api/ai-settings",json={"provider":provider,"acknowledge":True,"live_enabled":True}).status_code,200)
                self.sdk.models.list.assert_not_called()
                current = client.get('/api/projects/'+project.id).json()
                response = client.post('/api/projects/'+project.id+'/extractions',json={"expected_revision":current["revision"],"mode":"api"})
                self.assertEqual(response.status_code,202)
                self.assertEqual(wait_run(workspace,response.json()["run_id"]).status,"COMPLETED")
                current = client.get('/api/projects/'+project.id).json()
                for paper in current["papers"]:
                    current = client.patch('/api/projects/'+project.id+'/papers/'+paper["id"]+'/active-result',
                        json={"expected_revision":current["revision"],"result_id":paper["results"][-1]["id"]}).json()
                response = client.post('/api/projects/'+project.id+'/analyses',json={"expected_revision":current["revision"],"mode":"api"})
                self.assertEqual(response.status_code,202)
                self.assertEqual(wait_run(workspace,response.json()["run_id"]).status,"COMPLETED")
            self.assertEqual(self.sdk.responses.with_raw_response.parse.call_count,2)
            self.assertEqual(self.sdk.responses.create.call_count,2)
            for call in self.constructor.call_args_list:
                self.assertEqual(call.kwargs["max_retries"],0)
            before = client.get('/api/projects/'+project.id).json()
            self.assertTrue(all(e["locator_status"]=="LOCATED" for e in before["evidence"]))
            with workspace.repo.connection() as conn:
                hashes = {r[0]:hashlib.sha256(r[1].encode()).hexdigest() for r in conn.execute('select id,state from runs')}
        for offline in (True,False):
            restarted = self.app(data,offline)
            with TestClient(restarted,base_url="http://127.0.0.1") as client:
                caps = client.get('/api/capabilities').json()
                self.assertEqual(caps["hard_offline"],offline)
                self.assertFalse(caps["live_enabled"])
                self.assertTrue(all(not p["credential_configured"] and not p["consent_acknowledged"] and p["model"] is None
                                    for p in caps["providers"].values()))
                self.assertEqual(client.get('/api/projects/'+project.id).json(),before)
                if offline:
                    for provider in KEYS:
                        self.assertEqual(client.patch('/api/ai-settings',json={"provider":provider,"api_key":KEYS[provider],"model":MODELS[provider]}).status_code,200)
                        self.assertEqual(client.patch('/api/ai-settings',json={"provider":provider,"acknowledge":True,"live_enabled":True}).status_code,422)
                        self.assertEqual(client.post('/api/ai-settings/test-connection').status_code,422)
                self.assertEqual(client.post('/api/projects/'+project.id+'/analyses',json={"expected_revision":before["revision"],"mode":"api"}).status_code,422)
                with restarted.state.workspace.repo.connection() as conn:
                    self.assertEqual({r[0]:hashlib.sha256(r[1].encode()).hexdigest() for r in conn.execute('select id,state from runs')},hashes)
        self.assertEqual(self.sdk.responses.with_raw_response.parse.call_count,2)
        self.assertEqual(self.sdk.responses.create.call_count,2)
        self.sdk.models.list.assert_not_called()
        for file in data.rglob('*'):
            if file.is_file():
                for key in KEYS.values():self.assertNotIn(key.encode(),file.read_bytes())


if __name__ == '__main__':
    unittest.main()
