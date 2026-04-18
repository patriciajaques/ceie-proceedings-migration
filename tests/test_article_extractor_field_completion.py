"""Unit tests for field-completion payload and defensive merge."""

import json
import unittest

from src.services.article_extractor import ArticleExtractor


class TestFieldCompletionLlmPayload(unittest.TestCase):
    """_field_completion_llm_payload keeps metadata + authors, drops heavy keys."""

    def test_omits_references_and_page_lists(self) -> None:
        article = {
            "idJEMS": "99",
            "seq": 1,
            "titleOrig": "Título",
            "references": [{"description": "Very long reference text"}],
            "firstPages": [1, 2],
            "lastPages": [3, 4],
        }
        payload = ArticleExtractor._field_completion_llm_payload(article)
        self.assertNotIn("references", payload)
        self.assertNotIn("firstPages", payload)
        self.assertNotIn("lastPages", payload)
        self.assertEqual(payload.get("idJEMS"), "99")
        self.assertEqual(payload.get("titleOrig"), "Título")

    def test_includes_authors_when_present(self) -> None:
        authors = [{"name": "A", "email": ""}]
        article = {"idJEMS": "1", "authors": authors}
        payload = ArticleExtractor._field_completion_llm_payload(article)
        self.assertEqual(payload.get("authors"), authors)

    def test_json_dumps_payload_uses_utf8_literals(self) -> None:
        article = {"idJEMS": "1", "titleOrig": "Ação e coração"}
        payload = ArticleExtractor._field_completion_llm_payload(article)
        dumped = json.dumps(payload, ensure_ascii=False)
        self.assertIn("Ação", dumped)
        self.assertNotIn("\\u00", dumped)


class TestMergeFieldCompletionDict(unittest.TestCase):
    """_merge_field_completion_dict must not wipe prior text with empty LLM strings."""

    def test_keeps_prior_abstract_en_when_llm_empty_string(self) -> None:
        prior = {"abstractEn": "English abstract here.", "titleOrig": "T"}
        llm = {"abstractEn": ""}
        out = ArticleExtractor._merge_field_completion_dict(prior, llm)
        self.assertEqual(out["abstractEn"], "English abstract here.")

    def test_keeps_prior_keywords_when_llm_empty(self) -> None:
        prior = {"keywordsOrig": "a; b; c", "titleOrig": "T"}
        llm = {"keywordsOrig": "", "keywordsEn": ""}
        out = ArticleExtractor._merge_field_completion_dict(prior, llm)
        # normalize_keywords_field normalizes delimiters to comma-separated.
        self.assertEqual(out["keywordsOrig"], "a, b, c")

    def test_allows_llm_to_fill_when_prior_empty(self) -> None:
        prior = {"abstractEn": "", "titleOrig": "T"}
        llm = {"abstractEn": "New abstract."}
        out = ArticleExtractor._merge_field_completion_dict(prior, llm)
        self.assertIn("New abstract", out["abstractEn"])

    def test_strips_field_failure_reasons_from_output(self) -> None:
        prior = {"titleOrig": "T", "keywordsOrig": ""}
        llm = {
            "keywordsOrig": "one, two",
            "fieldFailureReasons": {"keywordsEn": "No English list in source."},
        }
        out = ArticleExtractor._merge_field_completion_dict(prior, llm)
        self.assertNotIn("fieldFailureReasons", out)
        self.assertIn("one", out["keywordsOrig"])


if __name__ == "__main__":
    unittest.main()
