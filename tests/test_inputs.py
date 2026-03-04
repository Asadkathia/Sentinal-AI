from scr.inputs import parse_unified_diff


def test_parse_unified_diff_file_and_ranges():
    diff = """diff --git a/a.py b/a.py
index 123..456 100644
--- a/a.py
+++ b/a.py
@@ -1,2 +1,4 @@
-a = 1
+b = 2
+c = 3
 d = 4
"""
    files = parse_unified_diff(diff)
    assert len(files) == 1
    file = files[0]
    assert file.path == "a.py"
    assert file.ranges[0].start_line == 1
    assert file.ranges[0].end_line == 4
    assert (1, "b = 2") in file.added_lines
    assert len(file.hunks) == 1
