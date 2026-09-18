"""测试环境配置：将数据库指向临时文件。

必须在 app 模块建立任何连接前设置；database.db_path() 在每次连接时
惰性读取环境变量，因此在导入 TestClient 前设置即可。
"""

import os
import tempfile

_TMP_DIR = tempfile.mkdtemp(prefix="soa_audit_test_")
os.environ["SOA_AUDIT_DB"] = os.path.join(_TMP_DIR, "test_audit.db")
