"""
通用工具模块说明：

这个文件负责保存多个模块都会用到的小工具函数。
它在整个项目流程中提供路径创建、时间生成、短标题处理等基础能力。
输入通常是路径、字符串或当前运行状态，输出是格式化后的值或已创建好的目录。
"""

from datetime import datetime, timezone
from pathlib import Path


def current_timestamp() -> str:
    """
    生成当前 UTC 时间字符串。

    参数：无。
    返回：ISO 8601 格式的 UTC 时间字符串。
    异常或特殊情况：正常情况下不会抛出异常。
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_directories(paths: list[Path]) -> None:
    """
    确保一组目录存在。

    参数：
        paths：需要创建或确认存在的目录路径列表。
    返回：无。
    异常或特殊情况：如果没有文件系统写入权限，Path.mkdir 可能抛出 OSError。
    """
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def short_title(title: str, max_length: int = 58) -> str:
    """
    生成适合图表展示的短标题。

    参数：
        title：论文标题。
        max_length：保留的最大字符数。
    返回：截断后的标题字符串。
    异常或特殊情况：标题为空时返回空字符串。
    """
    clean_title = (title or "").strip()
    if len(clean_title) <= max_length:
        return clean_title
    return clean_title[: max_length - 3] + "..."


def value_is_missing(value: object) -> bool:
    """
    判断字段值是否可以视为缺失。

    参数：
        value：任意字段值。
    返回：True 表示缺失，False 表示存在。
    异常或特殊情况：数字 0 不视为缺失，因为引用量可能真实为 0。
    """
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


if __name__ == "__main__":
    print("utils.py 是通用工具模块，通常由其他模块导入使用。")
    print(f"当前 UTC 时间示例：{current_timestamp()}")
