"""Shanghai University of Electric Power's registered public JYSD tenant."""
import re

from .gdut import jysd_enrich
from .ctgu import school_column_discover
from .gzhu import _table_grid
from .common import clean, decode_public_slots, evidence, observation


class ShiepAdapter:
    @staticmethod
    def discover(config, fetcher, cursor=None):
        return school_column_discover(config, fetcher, cursor, key="shiep", host="career.shiep.edu.cn")

    @staticmethod
    def enrich(candidate, fetcher):
        class Capture:
            response = None

            def get(self, url):
                self.response = fetcher.get(url)
                return self.response

        capture = Capture()
        result = jysd_enrich(candidate, capture, school_key="shiep", host="career.shiep.edu.cn")
        if capture.response is None or not result["patch"] or result["material_refs"][0]["parsing_status"] == "failed":
            return result
        document, _ = decode_public_slots(capture.response["text"])
        material = result["material_refs"][0]
        patch = result["patch"]
        # SHIEP embeds a three-column recruitment table in the announcement
        # body itself, rather than only using the platform's linked-job table.
        for table_index, table in enumerate(document.select(".details-mge .aContent table"), 1):
            headers = None
            for row_index, cells in _table_grid(table):
                if "招聘专业" in cells and "招聘岗位类别" in cells:
                    headers = cells
                    continue
                if not headers or len(cells) != len(headers):
                    continue
                major = cells[headers.index("招聘专业")]
                if not re.search(r"电气|电力|电网|继电保护|(?<!机械设计制造及其)自动化", major):
                    continue
                excerpt = "；".join(f"{key}：{value}" for key, value in zip(headers, cells))
                locator = f".details-mge .aContent [第{table_index}表第{row_index}行，招聘专业列]"
                proof = evidence(material, locator, excerpt)
                patch["relevance"] = "related"
                patch["field_observations"]["relevance"] = observation("known", "related", [proof])
                fragments = patch.setdefault("job_fragments", [])
                if len(fragments) < 8:
                    fragments.append({"text": clean(excerpt)[:2000], "scope": "partial", "evidence": [proof]})
                return result
        return result
