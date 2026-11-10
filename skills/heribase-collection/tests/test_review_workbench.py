import argparse
import importlib.util
import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path


SKILL = Path(__file__).resolve().parents[1]
TASK_SCRIPTS = SKILL.parent / "heribase-task-package" / "scripts"
sys.path.insert(0, str(TASK_SCRIPTS))
sys.path.insert(0, str(SKILL / "scripts"))

import task_package
import task_operations


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


builder = load_module("build_review_workbench", SKILL / "scripts" / "build_review_workbench.py")
pairing_builder = load_module("build_pairing_workbench", SKILL / "scripts" / "build_pairing_workbench.py")
server_module = load_module("serve_review_workbench", SKILL / "scripts" / "serve_review_workbench.py")


class ReviewWorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        created = task_package.create_task(
            argparse.Namespace(
                root=str(self.root),
                display_name="审核台测试",
                slug="review-ui",
                description="",
                timezone="Asia/Shanghai",
                created_by="test",
                now="2026-08-28T20:00:00+08:00",
            )
        )
        self.task_key = created["task_key"]
        self.task = self.root / self.task_key

    def tearDown(self):
        self.temporary.cleanup()

    def test_pairing_workbench_marks_low_confidence_candidate_for_review(self):
        timestamp = "2026-08-28T12:01:00+00:00"
        item = {
            "local_id": f"{self.task_key}:local-01", "item_key": "local-01", "legacy_ids": [], "version": 1, "status": "active",
            "lineage": {"derived_from": [], "superseded_by": []}, "source_refs": [],
            "evidence": [], "organization": {"pair_confidence": "medium", "pairing": "paired"}, "field_claims": {}, "resolved_fields": {},
            "active_identification": None, "review_projection": None, "collection_projection": None, "attention_flags": ["pairing_needs_confirmation"],
            "created_at": timestamp, "updated_at": timestamp,
        }
        input_path = self.root / "pairing-items.json"
        input_path.write_text(json.dumps([item], ensure_ascii=False), encoding="utf-8")
        task_operations.import_items(argparse.Namespace(root=str(self.root), task_key=self.task_key, expected_revision=1, actor="test", file=str(input_path), mode="merge"))
        result = pairing_builder.build_workbench(argparse.Namespace(root=str(self.root), task_key=self.task_key, output_name="pairing-workbench"))
        self.assertTrue(result["requires_review"])
        self.assertEqual(result["status_counts"]["needs_review"], 1)
        self.assertTrue((Path(result["output_path"]) / "index.html").is_file())

    def test_confirmed_pair_with_unknown_directions_still_requires_orientation_review(self):
        item = {
            "status": "active",
            "evidence": [
                {"source_id": "source-a", "role": "unknown", "is_primary": True},
                {"source_id": "source-b", "role": "unknown", "is_primary": True},
            ],
            "organization": {"pairing_state": "confirmed", "source_assignment": [{"source_id": "source-a", "role": "unknown"}, {"source_id": "source-b", "role": "unknown"}]},
            "attention_flags": [],
        }
        self.assertTrue(pairing_builder.needs_review(item))

    def test_pairing_workbench_copies_local_evidence_inside_document_root(self):
        original = self.root / "front.jpg"
        original.write_bytes(b"image-fixture")
        task_operations.ingest_source(argparse.Namespace(root=str(self.root), task_key=self.task_key, expected_revision=1, actor="test", file=str(original), kind="local_image", source_id="source-front", origin_type="local", origin_url=None, original_path=None, mime_type="image/jpeg", parent_source_id=None, sheet=None, row=None, column=None, cell=None, relationship_id=None))
        stamp = "2026-08-28T12:01:00+00:00"
        item = {"local_id": f"{self.task_key}:local-01", "item_key": "local-01", "legacy_ids": [], "version": 1, "status": "active", "lineage": {"derived_from": [], "superseded_by": []}, "source_refs": ["source-front"], "evidence": [{"evidence_id":"front","source_id":"source-front","role":"obverse","is_primary":True,"pair_confidence":0.5,"rationale":"fixture"}], "organization": {"pair_confidence":"medium"}, "field_claims": {}, "resolved_fields": {}, "active_identification":None,"review_projection":None,"collection_projection":None,"attention_flags":["pairing_needs_confirmation"],"created_at":stamp,"updated_at":stamp}
        payload = self.root / "evidence-item.json"
        payload.write_text(json.dumps([item]), encoding="utf-8")
        task_operations.import_items(argparse.Namespace(root=str(self.root), task_key=self.task_key, expected_revision=2, actor="test", file=str(payload), mode="merge"))
        result = pairing_builder.build_workbench(argparse.Namespace(root=str(self.root), task_key=self.task_key, output_name="pairing-workbench"))
        image = json.loads((Path(result["output_path"]) / "pairing-data.js").read_text()[len("window.COIN_PAIRING_DATA="):-2])["records"][0]["evidence"][0]["image"]
        self.assertTrue(image.startswith("evidence/"))
        self.assertTrue((Path(result["output_path"]) / image).is_file())

    def test_pairing_workbench_exposes_slab_label_claims_as_clues(self):
        """盒标字段必须进入配对审核数据，并与服务端身份明确区分。"""

        stamp = "2026-08-28T12:01:00+00:00"
        item = {
            "local_id": f"{self.task_key}:local-01", "item_key": "local-01", "legacy_ids": [], "version": 1, "status": "active",
            "lineage": {"derived_from": [], "superseded_by": []}, "source_refs": [], "evidence": [],
            "organization": {"type": "graded_slab", "pair_confidence": "high"},
            "field_claims": {"slab_label_analysis": {
                "source_id": "source-slab", "method": "visual_inspection", "analyzed_at": stamp, "confidence": 0.98,
                "fields": {"grade": {"raw_value": "PF 69 REVERSE PROOF", "normalized_value": "PF 69 REVERSE PROOF", "confidence": 0.98, "evidence_region": "label center"}},
            }},
            "resolved_fields": {}, "active_identification": None, "review_projection": None, "collection_projection": None,
            "attention_flags": [], "created_at": stamp, "updated_at": stamp,
        }
        input_path = self.root / "slab-items.json"
        input_path.write_text(json.dumps([item], ensure_ascii=False), encoding="utf-8")
        task_operations.import_items(argparse.Namespace(root=str(self.root), task_key=self.task_key, expected_revision=1, actor="test", file=str(input_path), mode="merge"))
        result = pairing_builder.build_workbench(argparse.Namespace(root=str(self.root), task_key=self.task_key, output_name="pairing-workbench"))
        data = json.loads((Path(result["output_path"]) / "pairing-data.js").read_text()[len("window.COIN_PAIRING_DATA="):-2])
        claim = data["records"][0]["slabLabel"]["fields"][0]
        self.assertEqual(claim["name"], "grade")
        self.assertEqual(claim["normalizedValue"], "PF 69 REVERSE PROOF")
        self.assertEqual(claim["evidenceRegion"], "label center")
        self.assertIn("标签读取线索", (Path(result["output_path"]) / "index.html").read_text(encoding="utf-8"))

    def test_review_workbench_copies_evidence_inside_document_root(self):
        """识别审核台必须能从自身静态根目录读取图片，不能依赖越界相对路径。"""

        original = self.root / "front.jpg"
        original.write_bytes(b"image-fixture")
        task_operations.ingest_source(argparse.Namespace(root=str(self.root), task_key=self.task_key, expected_revision=1, actor="test", file=str(original), kind="local_image", source_id="source-front", origin_type="local", origin_url=None, original_path=None, mime_type="image/jpeg", parent_source_id=None, sheet=None, row=None, column=None, cell=None, relationship_id=None))
        stamp = "2026-08-28T12:01:00+00:00"
        item = {"local_id": f"{self.task_key}:local-01", "item_key":"local-01", "legacy_ids":[], "version":1, "status":"active", "lineage":{"derived_from":[],"superseded_by":[]}, "source_refs":["source-front"], "evidence":[{"evidence_id":"front","source_id":"source-front","role":"obverse","is_primary":True,"pair_confidence":0.95,"rationale":"fixture"}], "organization":{}, "field_claims":{}, "resolved_fields":{}, "active_identification":None, "review_projection":None, "collection_projection":None, "attention_flags":[], "created_at":stamp, "updated_at":stamp}
        payload = self.root / "review-evidence-item.json"
        payload.write_text(json.dumps([item]), encoding="utf-8")
        task_operations.import_items(argparse.Namespace(root=str(self.root), task_key=self.task_key, expected_revision=2, actor="test", file=str(payload), mode="merge"))
        result = builder.build_workbench(argparse.Namespace(root=str(self.root), task_key=self.task_key, output_name="review-workbench"))
        data = (Path(result["output_path"]) / "review-data.js").read_text(encoding="utf-8")
        image = json.loads(data[len("(function(){window.COIN_REVIEW_DATA="):-7])["records"][0]["imageFront"]
        self.assertTrue(image.startswith("evidence/"))
        self.assertTrue((Path(result["output_path"]) / image).is_file())

    def test_review_workbench_displays_fields_from_immutable_identification_result(self):
        """审核员需要看见服务实际返回的币名、年份、铸厂和价格，而非仅内部 ID。"""

        raw_dir = self.task / "recognition" / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "attempt.json").write_text(json.dumps({"result": {
            "title": "Germany 1 pfennig 1990-J", "year": "1990", "mintMark": "J",
            "price": {"value": "$0.63"},
        }}), encoding="utf-8")
        item = {
            "local_id": f"{self.task_key}:local-01", "item_key": "local-01", "status": "active",
            "evidence": [], "organization": {}, "resolved_fields": {}, "attention_flags": [],
            "active_identification": {
                "status": "succeeded", "raw_response_ref": "recognition/raw/attempt.json",
                "currency_number": "DE-1", "uniq_uri": "variant-1",
            },
            "collection_projection": None,
        }
        record = builder.record_from_item(self.task, self.task / "derived" / "review-workbench", item, {})
        self.assertEqual(record["identification"]["name"], "Germany 1 pfennig 1990-J")
        self.assertEqual(record["identification"]["year"], "1990")
        self.assertEqual(record["identification"]["mintMark"], "J")
        self.assertEqual(record["identification"]["value"], "$0.63")
        self.assertNotIn("currencyNumber", record["identification"])
        self.assertNotIn("uniqUri", record["identification"])

    def test_generates_task_scoped_dual_track_workbench(self):
        timestamp = "2026-08-28T12:01:00+00:00"
        item = {
            "local_id": f"{self.task_key}:local-01",
            "item_key": "local-01",
            "legacy_ids": [],
            "version": 1,
            "status": "active",
            "lineage": {"derived_from": [], "superseded_by": []},
            "source_refs": [],
            "evidence": [],
            "organization": {"warnings": ["需要补充反面图片"]},
            "field_claims": {},
            "resolved_fields": {"title": {"value": "测试硬币"}, "year": {"value": "1964"}},
            "active_identification": None,
            "review_projection": None,
            "collection_projection": None,
            "attention_flags": [],
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        input_path = self.root / "items.json"
        input_path.write_text(json.dumps([item], ensure_ascii=False), encoding="utf-8")
        task_operations.import_items(
            argparse.Namespace(
                root=str(self.root),
                task_key=self.task_key,
                expected_revision=1,
                actor="test",
                file=str(input_path),
                mode="merge",
            )
        )
        result = builder.build_workbench(
            argparse.Namespace(root=str(self.root), task_key=self.task_key, output_name="review-workbench")
        )
        self.assertEqual(result["record_count"], 1)
        self.assertEqual(result["status_counts"]["unidentified"], 1)
        output = Path(result["output_path"])
        html = (output / "index.html").read_text(encoding="utf-8")
        data_js = (output / "review-data.js").read_text(encoding="utf-8")
        self.assertIn("review-handoff.js", html)
        self.assertIn("review-data.js", html)
        self.assertIn("get_review_decisions", (output / "review-handoff.js").read_text(encoding="utf-8"))
        self.assertIn("heribase-review:${storageScope}", html)
        self.assertIn("user_uniq_uri", html)
        self.assertIn(self.task_key, data_js)
        self.assertIn(f"{self.task_key}:local-01", data_js)

    def test_local_server_sets_origin_isolation_headers_and_stays_read_only(self):
        result = builder.build_workbench(
            argparse.Namespace(root=str(self.root), task_key=self.task_key, output_name="review-workbench")
        )
        output = Path(result["output_path"])
        server = server_module.ThreadingHTTPServer(
            ("127.0.0.1", 0), server_module.make_handler(output)
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/") as response:
                body = response.read().decode("utf-8")
                self.assertEqual(response.headers.get("Origin-Agent-Cluster"), "?1")
                self.assertEqual(response.headers.get("Permissions-Policy"), "tools=(self)")
                self.assertEqual(response.headers.get("Cache-Control"), "no-store")
                self.assertIn("HeriBase 硬币审核台", body)
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_address[1]}/",
                data=b"{}",
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(error.exception.code, 501)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
