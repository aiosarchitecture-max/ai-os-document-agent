import os
import tempfile

_test_db = tempfile.NamedTemporaryFile(prefix="aios-test-", suffix=".db", delete=False)
_test_db.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_test_db.name}"
os.environ["API_TOKEN"] = "test-token"
os.environ["APPROVAL_SIGNING_KEY"] = "test-signing-key"
