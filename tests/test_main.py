import unittest

from app import batch_main, main


class MainTests(unittest.TestCase):
    def test_launcher_exposes_run_function(self) -> None:
        self.assertTrue(callable(main.run))

    def test_batch_launcher_exposes_run_function(self) -> None:
        self.assertTrue(callable(batch_main.run))


if __name__ == "__main__":
    unittest.main()
