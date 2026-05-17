"""Tests – CV Module."""

import os
import tempfile
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.cv_module.services import collect_cvs_from_local, rank_all_cvs, package_results


class TestCVCollection(TestCase):

    def test_collect_from_local_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Create dummy CV files
            for name in ["cv_ali.pdf", "cv_rahim.docx", "readme.txt"]:
                open(os.path.join(tmp, name), "w").close()

            results = collect_cvs_from_local(tmp)
            # Should only pick up .pdf and .docx
            fnames = [os.path.basename(r) for r in results]
            self.assertIn("cv_ali.pdf", fnames)
            self.assertIn("cv_rahim.docx", fnames)
            self.assertNotIn("readme.txt", fnames)

    def test_collect_from_nonexistent_dir_raises(self):
        with self.assertRaises(FileNotFoundError):
            collect_cvs_from_local("/nonexistent/path/xyz")


class TestCVScoring(TestCase):

    @patch("apps.cv_module.services.get_llm_client")
    @patch("apps.cv_module.services.extract_text_from_cv")
    def test_rank_all_cvs_sorted_by_score(self, mock_extract, mock_llm_factory):
        # CV text needs to be > 30 chars to clear the no-text-skip guard.
        long_text = "Candidate CV with sufficient text content for the LLM to score against requirements."
        mock_extract.side_effect = [long_text, long_text, long_text]

        mock_llm = MagicMock()
        responses = [
            '{"candidate_name": "Ali", "match_score": 85, "key_qualifications": "Django, Python"}',
            '{"candidate_name": "Rahim", "match_score": 60, "key_qualifications": "React"}',
            '{"candidate_name": "Karim", "match_score": 92, "key_qualifications": "Django, PostgreSQL"}',
        ]
        mock_llm.complete.side_effect = responses
        mock_llm_factory.return_value = mock_llm

        files = ["/tmp/a.pdf", "/tmp/b.pdf", "/tmp/c.pdf"]
        ranked = rank_all_cvs(files, "Django developer with PostgreSQL experience")

        # Should be sorted highest first
        self.assertEqual(ranked[0]["candidate_name"], "Karim")
        self.assertEqual(ranked[0]["match_score"], 92)
        self.assertEqual(ranked[1]["candidate_name"], "Ali")
        self.assertEqual(ranked[2]["candidate_name"], "Rahim")
        # Ranks assigned correctly
        self.assertEqual(ranked[0]["rank"], 1)
        self.assertEqual(ranked[2]["rank"], 3)

    @patch("apps.cv_module.services.get_llm_client")
    def test_score_cv_llm_failure_returns_zero(self, mock_llm_factory):
        from apps.cv_module.services import score_cv

        mock_llm = MagicMock()
        mock_llm.complete.side_effect = RuntimeError("LLM error")
        mock_llm_factory.return_value = mock_llm

        # Long enough text to actually attempt scoring (passes 30-char guard).
        result = score_cv(
            "Some candidate CV text long enough to be processed by the scorer.",
            "requirements",
        )
        self.assertEqual(result["match_score"], 0)
        # On LLM failure name comes back empty (no longer fabricating
        # the literal "Unknown").
        self.assertEqual(result["candidate_name"], "")


class TestCVPackaging(TestCase):

    @patch("apps.cv_module.services.get_llm_client")
    def test_package_results_creates_excel(self, _):
        """package_results writes a single Excel summary (no ZIP).

        The function used to create a ZIP containing CV files + a CSV
        summary. As of the database-first refactor it writes a
        single .xlsx summary instead — CV files stay on disk where
        they were and the candidates land in the database via
        upsert_candidate_profile().
        """
        with tempfile.TemporaryDirectory() as tmp_out:
            with tempfile.TemporaryDirectory() as tmp_cvs:
                cv_files = []
                for i in range(5):
                    p = os.path.join(tmp_cvs, f"candidate_{i}.pdf")
                    with open(p, "wb") as f:
                        f.write(b"%PDF-dummy")
                    cv_files.append(p)

                ranked = [
                    {
                        "rank": i + 1,
                        "file_path": cv_files[i],
                        "file_name": f"candidate_{i}.pdf",
                        "candidate_name": f"Candidate {i}",
                        "match_score": 90 - i * 5,
                        "key_qualifications": "Python",
                    }
                    for i in range(5)
                ]

                xlsx_path = package_results(
                    ranked, top_n=3, output_dir=tmp_out, job_id=1,
                )
                self.assertTrue(os.path.isfile(xlsx_path))
                self.assertTrue(xlsx_path.endswith(".xlsx"))