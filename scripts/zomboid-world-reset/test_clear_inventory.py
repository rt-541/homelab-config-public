import unittest
from clear_inventory import strip_inventory


class TestStripInventory(unittest.TestCase):
    def test_truncates_at_first_module_item_id(self):
        # Identity section ends; inventory begins with a Base.Item record.
        # The identity block must be >= MIN_SCAN_OFFSET bytes; pad with nulls to
        # simulate a realistic-sized stats/identity section.
        from clear_inventory import MIN_SCAN_OFFSET
        identity = b'IDENTITY_BLOCK_HEADER' + b'\x00' * (MIN_SCAN_OFFSET + 10)
        inventory = b'\x00\x10Base.HuntingKnife' + b'TRAILING_INVENTORY_BYTES'
        blob = identity + inventory
        result = strip_inventory(blob)
        self.assertNotIn(b'Base.HuntingKnife', result)
        self.assertNotIn(b'TRAILING_INVENTORY_BYTES', result)
        self.assertIn(b'IDENTITY_BLOCK_HEADER', result)

    def test_returns_blob_unchanged_when_no_item_id_found(self):
        blob = b'just an identity blob with no items'
        self.assertEqual(strip_inventory(blob), blob)

    def test_truncation_skips_module_id_strings_inside_identity_section(self):
        # MIN_SCAN_OFFSET guards against module-ID-looking substrings that appear
        # in the first portion of the blob (e.g., embedded in binary stats fields).
        # A Base.Foo match at offset < MIN_SCAN_OFFSET must NOT cause truncation.
        from clear_inventory import MIN_SCAN_OFFSET
        # Plant a plausible module-ID substring at offset 5 (well inside the floor).
        early_false_positive = b'\x00\x00\x00\x00\x00Base.EarlyFalsePositive'
        # Pad to push past the floor, then add the real first inventory item.
        padding = b'\x00' * (MIN_SCAN_OFFSET - len(early_false_positive) + 5)
        real_inventory = b'Base.HuntingKnife' + b'INVENTORY_DATA'
        blob = early_false_positive + padding + real_inventory
        result = strip_inventory(blob)
        # The early false-positive is before MIN_SCAN_OFFSET — blob must not be
        # truncated there; the early bytes must survive.
        self.assertIn(b'Base.EarlyFalsePositive', result)
        # The real inventory item (past the floor) must be stripped.
        self.assertNotIn(b'INVENTORY_DATA', result)

    def test_skips_handcraft_last_recipe_false_positive(self):
        # The blob identity section contains handcraftLastRecipe followed by a Base.*
        # recipe name. This must NOT be treated as the inventory boundary.
        identity = b'\x00\x13handcraftLastRecipe\x00\x00\x11Base.DisinfectRag'
        inventory_start = b'\x00\x0fBase.HuntingKnife'
        blob = identity + b'\x00' * 200 + inventory_start + b'INVENTORY_DATA'
        result = strip_inventory(blob)
        # Inventory item should be stripped
        self.assertNotIn(b'INVENTORY_DATA', result)
        # Identity section must be intact
        self.assertIn(b'handcraftLastRecipe', result)

    def test_skips_build_last_recipe_false_positive(self):
        # buildLastRecipe is another identity-section field that embeds a Base.* value.
        identity = b'\x00\x0fbuildLastRecipe\x00\x00\x14Base.BarricadePlanks'
        inventory_start = b'\x00\x0fBase.HuntingKnife'
        blob = identity + b'\x00' * 200 + inventory_start + b'MORE_INVENTORY'
        result = strip_inventory(blob)
        self.assertNotIn(b'MORE_INVENTORY', result)
        self.assertIn(b'buildLastRecipe', result)

    def test_idempotent_on_already_stripped_blob(self):
        # Stripping a blob that has no inventory returns it unchanged.
        identity = b'IDENTITY_BLOCK_HEADER_WITH_NO_ITEMS'
        result1 = strip_inventory(identity)
        result2 = strip_inventory(result1)
        self.assertEqual(result1, result2)

    def test_short_blob_returned_unchanged(self):
        # A blob shorter than MIN_SCAN_OFFSET is returned unchanged (no scan attempted).
        blob = b'tiny'
        self.assertEqual(strip_inventory(blob), blob)


if __name__ == '__main__':
    unittest.main()
