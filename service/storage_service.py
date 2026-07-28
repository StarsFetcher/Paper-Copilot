"""
Local File System Storage Service
==================================
取代 MinIO 对象存储，使用本地文件系统直接管理 PDF 文件和向量库备份。

接口与原有的 MinioService 保持一致，确保上层调用代码改动最小化。

功能包括:
    - PDF 文件的本地保存、读取、删除
    - 向量数据库的本地备份与恢复
    - 文件列表查询
"""

import hashlib
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

from config.settings import settings
from utils.logger import setup_logger

logger = setup_logger(__name__)


class LocalStorageService:
    """
    本地文件系统存储服务

    所有操作均在本地磁盘完成，无需外部服务依赖。
    论文 PDF 存储在 settings.PAPERS_DIR 下，
    向量库备份存储在 settings.BACKUPS_DIR 下。
    """

    def __init__(self):
        self.papers_dir: Path = Path(settings.PAPERS_DIR)
        self.backups_dir: Path = Path(settings.BACKUPS_DIR)
        self._connected: bool = False

    # =================================================================
    # 连接管理（接口兼容）
    # =================================================================

    def connect(self) -> bool:
        """
        确保本地存储目录存在。

        在应用启动时调用一次，自动创建所需的目录结构。

        Returns:
            True 表示目录就绪，False 表示创建失败（如磁盘权限问题）
        """
        try:
            self.papers_dir.mkdir(parents=True, exist_ok=True)
            self.backups_dir.mkdir(parents=True, exist_ok=True)
            self._connected = True
            logger.info(
                f"本地存储就绪: papers={self.papers_dir}, "
                f"backups={self.backups_dir}"
            )
            return True
        except Exception as e:
            logger.error(f"创建存储目录失败: {e}")
            self._connected = False
            return False

    def is_connected(self) -> bool:
        """本地文件系统始终可用（目录已创建的前提下）"""
        return self._connected

    # =================================================================
    # PDF 文件操作
    # =================================================================

    def upload_pdf(self, file_data: bytes, file_name: str) -> Optional[str]:
        """
        将 PDF 文件保存到本地 papers 目录。

        Args:
            file_data: PDF 文件的完整二进制数据
            file_name: 原始文件名

        Returns:
            成功时返回对象路径（如 papers/{md5}_{filename}），失败时返回 None

        命名规则:
            使用文件内容 MD5 前 8 位作为前缀，防止同名文件覆盖。
            最终文件名: {md5_prefix}_{原始文件名}
        """
        if not self._connected:
            logger.error("保存失败：本地存储未初始化")
            return None

        try:
            content_hash = hashlib.md5(file_data).hexdigest()[:8]
            disk_name = f"{content_hash}_{file_name}"
            file_path = self.papers_dir / disk_name

            file_path.write_bytes(file_data)

            object_name = f"papers/{disk_name}"
            logger.info(
                f"PDF 保存成功: path={file_path}, "
                f"size={len(file_data) / 1024:.1f} KB"
            )
            return object_name

        except Exception as e:
            logger.error(f"PDF 保存失败: {e}")
            return None

    def download_pdf(self, object_name: str) -> Optional[bytes]:
        """
        从本地 papers 目录读取 PDF 文件。

        Args:
            object_name: 对象路径（如 papers/{hash}_{filename}）

        Returns:
            成功时返回文件二进制数据，文件不存在时返回 None
        """
        if not self._connected:
            return None

        try:
            # 去掉 "papers/" 前缀，得到实际文件名
            pdf_name = object_name.replace("papers/", "", 1)
            file_path = self.papers_dir / pdf_name

            if not file_path.exists():
                logger.warning(f"PDF 文件不存在: {file_path}")
                return None

            data = file_path.read_bytes()
            logger.info(f"PDF 读取成功: path={file_path}, size={len(data)} bytes")
            return data

        except Exception as e:
            logger.error(f"PDF 读取失败: {e}")
            return None

    def delete_pdf(self, object_name: str) -> bool:
        """
        从本地 papers 目录删除 PDF 文件。

        Args:
            object_name: 对象路径

        Returns:
            True 表示删除成功（或文件本就不存在），False 表示失败
        """
        if not self._connected:
            return False

        try:
            pdf_name = object_name.replace("papers/", "", 1)
            file_path = self.papers_dir / pdf_name

            if file_path.exists():
                file_path.unlink()
                logger.info(f"PDF 删除成功: {file_path}")
            else:
                logger.info(f"PDF 文件不存在，无需删除: {file_path}")

            return True

        except Exception as e:
            logger.error(f"PDF 删除失败: {e}")
            return False

    # =================================================================
    # 向量库备份操作
    # =================================================================

    def upload_vector_backup(
        self,
        local_dir: str,
        backup_name: Optional[str] = None,
    ) -> bool:
        """
        将本地向量数据库目录备份到 backups 目录。

        使用目录复制方式（比 ZIP 更快，且方便直接查看）。

        Args:
            local_dir: 向量数据库源目录路径
            backup_name: 备份子目录名称（默认 "vector_store_backup"）

        Returns:
            成功时返回 True，失败时返回 False
        """
        if backup_name is None:
            backup_name = "vector_store_backup"

        if not self._connected:
            logger.error("备份失败：本地存储未初始化")
            return False

        src_path = Path(local_dir)
        if not src_path.exists() or not any(src_path.iterdir()):
            logger.warning(f"向量库目录为空或不存在: {local_dir}，跳过备份")
            return False

        try:
            # 使用目录复制（去掉 .zip 后缀，方便直接查看）
            backup_dir = self.backups_dir / backup_name.replace(".zip", "")
            if backup_dir.exists():
                shutil.rmtree(str(backup_dir))
            shutil.copytree(str(src_path), str(backup_dir))
            logger.info(f"向量库备份成功: {src_path} -> {backup_dir}")
            return True

        except Exception as e:
            logger.error(f"向量库备份失败: {e}", exc_info=True)
            return False

    def download_vector_backup(
        self,
        backup_name: Optional[str] = None,
        output_dir: Optional[str] = None,
    ) -> bool:
        """
        从本地 backups 目录恢复向量数据库。

        优先尝试 ZIP 文件恢复，其次尝试目录复制恢复。
        应用启动时调用，用于恢复上次持久化的向量库状态。

        Args:
            backup_name: 备份名称（默认 "vector_store_backup"）
            output_dir: 恢复目标目录（默认使用配置中的 VECTOR_DB_PATH）

        Returns:
            成功时返回 True，备份不存在或失败时返回 False
        """
        if backup_name is None:
            backup_name = "vector_store_backup"
        if output_dir is None:
            output_dir = settings.VECTOR_DB_PATH

        if not self._connected:
            return False

        output_path = Path(output_dir)

        # 尝试 ZIP 格式恢复（兼容旧版 MinIO 备份）
        zip_path = self.backups_dir / f"{backup_name}.zip"
        if zip_path.exists():
            try:
                output_path.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(str(output_path))
                file_count = len(list(output_path.rglob("*")))
                logger.info(
                    f"向量库从 ZIP 备份恢复成功: {file_count} 个文件 -> {output_dir}"
                )
                return True
            except Exception as e:
                logger.error(f"ZIP 备份解压失败: {e}")

        # 尝试目录格式恢复
        backup_dir = self.backups_dir / backup_name
        if backup_dir.exists() and backup_dir.is_dir():
            try:
                output_path.mkdir(parents=True, exist_ok=True)
                # 清空目标目录
                if output_path.exists():
                    for item in output_path.iterdir():
                        if item.is_file():
                            item.unlink()
                        elif item.is_dir():
                            shutil.rmtree(str(item))
                # 复制备份文件
                for item in backup_dir.iterdir():
                    dest = output_path / item.name
                    if item.is_file():
                        shutil.copy2(str(item), str(dest))
                    elif item.is_dir():
                        if dest.exists():
                            shutil.rmtree(str(dest))
                        shutil.copytree(str(item), str(dest))
                file_count = len(list(output_path.rglob("*")))
                logger.info(
                    f"向量库从目录备份恢复成功: {file_count} 个文件 -> {output_dir}"
                )
                return True
            except Exception as e:
                logger.error(f"目录备份恢复失败: {e}")
                return False

        logger.info(f"未找到向量库备份 ({self.backups_dir / backup_name})")
        return False

    # =================================================================
    # 列表查询
    # =================================================================

    def list_objects(self, prefix: str = "") -> List[Dict]:
        """
        列出本地存储目录中的文件。

        Args:
            prefix: 路径前缀过滤
                    - "papers/"  → 列出 papers 目录
                    - "backups/" → 列出 backups 目录
                    - ""         → 默认列出 papers 目录

        Returns:
            文件信息列表，每项包含 name, size, last_modified
        """
        if not self._connected:
            return []

        try:
            if prefix.startswith("backups"):
                base_dir = self.backups_dir
                path_prefix = "backups/"
            else:
                base_dir = self.papers_dir
                path_prefix = "papers/"

            if not base_dir.exists():
                return []

            objects = []
            for fpath in sorted(base_dir.rglob("*")):
                if fpath.is_file() and not fpath.name.startswith("."):
                    stat = fpath.stat()
                    # 相对路径（相对于 base_dir），加上 path_prefix
                    rel_path = str(fpath.relative_to(base_dir))
                    objects.append({
                        "name": f"{path_prefix}{rel_path}",
                        "size": stat.st_size,
                        "last_modified": str(
                            datetime.fromtimestamp(stat.st_mtime)
                        ),
                    })

            return objects

        except Exception as e:
            logger.error(f"列出文件失败: {e}")
            return []


# ================================================================
# 全局单例（模块级）
# ================================================================
# 使用模块级变量维护全局唯一的 LocalStorageService 实例，
# 确保所有 API 路由共享同一个存储服务实例。

_storage_service_instance: Optional[LocalStorageService] = None


def get_storage_service() -> LocalStorageService:
    """
    获取全局唯一的 LocalStorageService 实例。

    首次调用时创建实例（不立即创建目录，由 connect() 负责），
    后续调用返回同一个实例。

    Returns:
        LocalStorageService 单例实例
    """
    global _storage_service_instance
    if _storage_service_instance is None:
        _storage_service_instance = LocalStorageService()
    return _storage_service_instance
