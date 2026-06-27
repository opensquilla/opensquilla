"""Unit tests for opensquilla.contrib.swebench.patch."""

from opensquilla.contrib.swebench.patch import clean_patch, is_empty_patch

NORMAL_DIFF = """\
diff --git a/src/foo.py b/src/foo.py
index 1234567..89abcde 100644
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,3 +1,3 @@
-old line
+new line
 context
"""

SETUP_FILE_DIFF = """\
diff --git a/pyproject.toml b/pyproject.toml
index 1234567..89abcde 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,3 +1,3 @@
-version = "1.0"
+version = "2.0"
"""

BINARY_DIFF = """\
diff --git a/img.png b/img.png
Binary files a/img.png and b/img.png differ
"""

NON_ASCII_DIFF = """\
diff --git a/路径/文件.py b/路径/文件.py
index 1234567..89abcde 100644
--- a/路径/文件.py
+++ b/路径/文件.py
@@ -1,1 +1,1 @@
-old
+new
"""


class TestCleanPatch:
    def test_keeps_normal_diff(self):
        cleaned = clean_patch(NORMAL_DIFF)
        assert "src/foo.py" in cleaned
        assert "+new line" in cleaned
        assert cleaned.endswith("\n")

    def test_strips_setup_files(self):
        cleaned = clean_patch(SETUP_FILE_DIFF + NORMAL_DIFF)
        assert "pyproject.toml" not in cleaned
        assert "src/foo.py" in cleaned

    def test_strips_lock_files(self):
        lock_diff = SETUP_FILE_DIFF.replace("pyproject.toml", "package-lock.json")
        cleaned = clean_patch(lock_diff + NORMAL_DIFF)
        assert "package-lock.json" not in cleaned
        assert "src/foo.py" in cleaned

    def test_strips_binary_diff(self):
        cleaned = clean_patch(BINARY_DIFF + NORMAL_DIFF)
        assert "img.png" not in cleaned
        assert "src/foo.py" in cleaned

    def test_strips_non_ascii_filenames(self):
        cleaned = clean_patch(NON_ASCII_DIFF + NORMAL_DIFF)
        assert "文件" not in cleaned
        assert "src/foo.py" in cleaned

    def test_empty_input(self):
        assert clean_patch("") == ""
        assert clean_patch("   \n  ") == ""

    def test_all_stripped_returns_empty(self):
        assert clean_patch(SETUP_FILE_DIFF) == ""


class TestIsEmptyPatch:
    def test_empty_string(self):
        assert is_empty_patch("")
        assert is_empty_patch("   ")

    def test_headers_only(self):
        headers = (
            "diff --git a/foo.py b/foo.py\n"
            "index 1234567..89abcde 100644\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
        )
        assert is_empty_patch(headers)

    def test_real_change(self):
        assert not is_empty_patch(NORMAL_DIFF)
