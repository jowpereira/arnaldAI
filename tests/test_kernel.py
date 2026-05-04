from pathlib import Path
import json
import tempfile
import unittest

from arnaldo.kernel import ArnaldoKernel


class KernelTest(unittest.TestCase):
    def test_run_generates_generic_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = ArnaldoKernel().run(
                "Crie um plano inicial para uma ferramenta B2B de automacao",
                output_dir=Path(tmp),
            )

            self.assertTrue(result.files["intent_ir"].exists())
            self.assertTrue(result.files["task_ir"].exists())
            self.assertTrue(result.files["organization_ir"].exists())
            self.assertTrue(result.files["artifact"].exists())
            self.assertTrue(result.files["evidence"].exists())

            task_ir = json.loads(result.files["task_ir"].read_text(encoding="utf-8"))
            self.assertEqual(task_ir["context"]["scope"], "generic")
            self.assertEqual(task_ir["goal"]["type"], "create_or_generate")
            self.assertNotIn("business" + "_research", json.dumps(task_ir))


if __name__ == "__main__":
    unittest.main()
