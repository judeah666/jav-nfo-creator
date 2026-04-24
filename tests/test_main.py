import unittest

from app import main


class MainTests(unittest.TestCase):
    def test_launcher_exposes_run_function(self) -> None:
        self.assertTrue(callable(main.run))


if __name__ == "__main__":
    unittest.main()
