import io
import pathlib
import tarfile
import tempfile

from tools.host_tree import _unpack


def test_unpack_directory_entry_raises_assertion():
    """
    The current implementation of ``_unpack`` asserts that ``tarfile.extractfile`` returns a file‑like
    object.  For directory members ``extractfile`` returns ``None`` and the assertion fails.
    This test deliberately creates a tarball containing a directory entry and calls ``_unpack``.
    The test expects the call to succeed; therefore it will FAIL (raise an AssertionError) on the
    existing code if the reviewer’s claim is true.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = pathlib.Path(tmpdir)

        # Create a tarball with a directory entry and a regular file inside it.
        tar_path = tmp_path / "archive.tar"
        with tarfile.open(tar_path, "w") as tf:
            # Directory entry
            dir_info = tarfile.TarInfo(name="mydir/")
            dir_info.type = tarfile.DIRTYPE
            dir_info.mode = 0o755
            dir_info.mtime = 0
            tf.addfile(dir_info)

            # Regular file entry inside the directory
            file_data = b"hello world"
            file_info = tarfile.TarInfo(name="mydir/file.txt")
            file_info.size = len(file_data)
            file_info.mode = 0o644
            file_info.mtime = 0
            tf.addfile(file_info, io.BytesIO(file_data))

        # Destination directory for unpacking
        dest = tmp_path / "dest"

        # The call is expected to succeed; if the assertion triggers, the test will fail.
        _unpack(tar_path, dest)
