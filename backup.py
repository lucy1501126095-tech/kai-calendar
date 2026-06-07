"""数据库备份管理"""

import os
import shutil
from datetime import datetime


class BackupManager:
    def __init__(self, db_path: str, backup_dir: str, max_backups: int = 4):
        self.db_path = db_path
        self.backup_dir = backup_dir
        self.max_backups = max_backups
        os.makedirs(backup_dir, exist_ok=True)

    def create_backup(self, reason: str = "scheduled") -> str:
        """创建一份备份，返回备份文件路径"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_name = f"kai_calendar_{reason}_{timestamp}.db"
        backup_path = os.path.join(self.backup_dir, backup_name)
        shutil.copy2(self.db_path, backup_path)
        self._cleanup_old_backups()
        return backup_path

    def _cleanup_old_backups(self):
        """保留最近的N份备份，删除更旧的"""
        backups = sorted(
            [f for f in os.listdir(self.backup_dir) if f.endswith('.db')],
            key=lambda f: os.path.getmtime(os.path.join(self.backup_dir, f)),
            reverse=True
        )
        for old in backups[self.max_backups:]:
            os.remove(os.path.join(self.backup_dir, old))

    def list_backups(self) -> list:
        """列出所有备份"""
        backups = []
        for f in sorted(os.listdir(self.backup_dir), reverse=True):
            if f.endswith('.db'):
                path = os.path.join(self.backup_dir, f)
                backups.append({
                    'filename': f,
                    'size_kb': round(os.path.getsize(path) / 1024, 1),
                    'created': datetime.fromtimestamp(
                        os.path.getmtime(path)
                    ).strftime('%Y-%m-%d %H:%M'),
                })
        return backups
