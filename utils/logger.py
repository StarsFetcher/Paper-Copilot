"""
日志配置模块
============
提供统一的日志记录器，支持控制台彩色输出和文件持久化双通道。
所有模块通过 `setup_logger(__name__)` 获取各自的 logger 实例，
自动继承全局配置。

使用方式:
    from utils.logger import setup_logger
    logger = setup_logger(__name__)
    logger.info("这是一条日志")
"""

import logging
import sys
from pathlib import Path

from config.settings import settings


def setup_logger(name: str = "PaperCopilot") -> logging.Logger:
    """
    初始化并返回一个命名的日志记录器。

    特性:
        - 仅首次调用时创建 handler，后续调用返回已有 logger
        - 控制台输出使用标准流，文件输出写入 data/logs/app.log
        - 日志级别由 settings.LOG_LEVEL 控制

    Args:
        name: 日志记录器名称（通常传入 __name__）

    Returns:
        配置完成的 logging.Logger 实例
    """
    logger = logging.getLogger(name)

    # 避免重复添加 handler（幂等性保证）
    if logger.handlers:
        return logger

    # 设置全局日志级别
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logger.setLevel(level)

    # ----------------------------------------------------------
    # 日志格式定义
    # ----------------------------------------------------------
    # 控制台格式: 带颜色高亮的时间戳 + 级别 + 模块名 + 函数位置 + 消息
    console_format = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-25s | "
        "%(funcName)s:%(lineno)-4d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # 文件格式: 与控制台一致
    file_format = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-25s | "
        "%(funcName)s:%(lineno)-4d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ----------------------------------------------------------
    # 控制台 Handler
    # ----------------------------------------------------------
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)  # 控制台可以看 DEBUG 细节
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # ----------------------------------------------------------
    # 文件 Handler（自动创建日志目录）
    # ----------------------------------------------------------
    log_dir = Path(settings.PROJECT_ROOT) / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(
        log_dir / "app.log",
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)  # 文件记录所有级别日志
    file_handler.setFormatter(file_format)
    logger.addHandler(file_handler)

    # 防止日志向上传播到 root logger（避免重复输出）
    logger.propagate = False

    return logger
