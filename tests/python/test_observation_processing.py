"""Pure fixture coverage: these tests never inspect or operate the desktop."""
from pathlib import Path
import math
import struct
import sys
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'pcucp-next' / 'python'))
from pcucp_cli.observation_processing import (
    decode_png, fuse_ocr_uia, match_ocr_candidates, normalize_ocr_text,
    score_ocr_text, screenshot_diff,
)


def word(text, x=0, y=0, width=20, height=10, **extra):
    return dict(text=text, x=x, y=y, width=width, height=height, **extra)


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(data, zlib.crc32(kind)) & 0xffffffff)


def png(width=2, height=2, channels=4, filters=None, pixels=None):
    """Independent fixture encoder, all five PNG predictors."""
    pixels = pixels or bytes((i * 31 + 7) % 256 for i in range(width * height * channels))
    filters = filters or [0] * height
    stride = width * channels
    previous = bytes(stride)
    raw = bytearray()
    for y in range(height):
        row = pixels[y * stride:(y + 1) * stride]
        f = filters[y]
        raw.append(f)
        for i, value in enumerate(row):
            a, b, c = row[i - channels] if i >= channels else 0, previous[i], previous[i - channels] if i >= channels else 0
            if f == 0: prediction = 0
            elif f == 1: prediction = a
            elif f == 2: prediction = b
            elif f == 3: prediction = (a + b) // 2
            else:
                estimate = a + b - c
                distances = (abs(estimate - a), abs(estimate - b), abs(estimate - c))
                prediction = (a, b, c)[distances.index(min(distances))]
            raw.append((value - prediction) & 255)
        previous = row
    header = struct.pack('>IIBBBBB', width, height, 8, 6 if channels == 4 else 2, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')


class OcrMatchingTests(unittest.TestCase):
    def test_normalization_matches_legacy_unicode_rules(self):
        self.assertEqual(normalize_ocr_text('  ＳＡＶＥ—Ａｓ!\t설정 １２3  '), 'save as 설정 123')
        self.assertEqual(normalize_ocr_text('가'), '가')
        self.assertEqual(normalize_ocr_text('Straße'), 'straße')  # lower(), not casefold()
        self.assertEqual(normalize_ocr_text(None), '')

    def test_scores_match_legacy(self):
        self.assertEqual(score_ocr_text('Save', 'ＳＡＶＥ!', 'exact'), 100)
        self.assertEqual(score_ocr_text('Save', 'Save changes', 'prefix'), 80)
        self.assertEqual(score_ocr_text('Save', 'Save changes', 'contains'), 70)
        self.assertEqual(score_ocr_text('Save', 'Changes: Save', 'contains'), 60)
        self.assertEqual(score_ocr_text('Save', 'Sava', 'fuzzy'), 75)
        self.assertEqual(score_ocr_text('Save', 'Sava', 'contains'), 0)
        for invalid in ('unknown', [], {}, None):
            with self.assertRaises(ValueError): score_ocr_text('x', 'y', invalid)

    def test_empty_and_punctuation_query_rejected(self):
        for query in ('', ' ', '!!!'):
            with self.subTest(query=query), self.assertRaises(ValueError):
                match_ocr_candidates({}, query)

    def test_word_ngrams_have_tighter_geometry(self):
        body = {'lines': [{'text': 'Save As Document', 'words': [word('Save'), word('As', 25, width=10), word('Document', 40, width=60)]}]}
        result = match_ocr_candidates(body, 'Save As', 'exact')
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['top']['scope'], 'word_ngram')
        self.assertEqual(result['top']['n'], 2)
        self.assertEqual(result['top']['width'], 35)
        self.assertEqual(result['top']['cx'], 17.5)
        self.assertEqual(result['top']['coordinate_space'], 'image_pixels')
        self.assertFalse(result['actionable'])

    def test_three_word_ngram_and_no_cross_line_ngrams(self):
        lines = [{'text': 'one two three four', 'words': [word('one'), word('two', 21), word('three', 42), word('four', 63)]},
                 {'text': 'five', 'words': [word('five', 0, 20)]}]
        result = match_ocr_candidates({'lines': lines}, 'one two three', 'exact')
        self.assertEqual(result['top']['n'], 3)
        self.assertEqual(match_ocr_candidates({'lines': lines}, 'four five', 'exact')['status'], 'not_found')

    def test_single_token_skips_ngrams(self):
        result = match_ocr_candidates({'lines': [{'text': 'Save As', 'words': [word('Save'), word('As', 25)]}]}, 'Save')
        self.assertEqual(result['top']['scope'], 'word')
        self.assertFalse(any(c['scope'] == 'word_ngram' for c in result['candidates']))

    def test_flat_nested_word_dedup_and_same_box_not_ambiguous(self):
        w = word('Save')
        result = match_ocr_candidates({'words': [w], 'lines': [{'text': 'Save', 'words': [w]}]}, 'Save')
        self.assertEqual(result['candidate_count'], 2)  # one word and one line
        self.assertFalse(result['ambiguous'])
        self.assertEqual(result['top']['scope'], 'word')

    def test_ambiguity_survives_limit_one(self):
        result = match_ocr_candidates({'words': [word('Save'), word('Save', 50)]}, 'Save', limit=1)
        self.assertTrue(result['ambiguous'])
        self.assertTrue(result['truncated'])
        self.assertEqual(result['candidate_count'], 2)
        self.assertEqual(result['status'], 'partial')

    def test_legacy_rect_alias_and_nested_payload(self):
        result = match_ocr_candidates({'ocr': {'words': [{'text': '설정', 'x': 2, 'y': 4, 'w': 20, 'h': 10}]}}, '설정')
        self.assertEqual(result['top']['width'], 20)
        self.assertEqual(result['top']['cy'], 9)

    def test_min_score_and_fuzzy_opt_in(self):
        body = {'words': [word('Sava')]}
        self.assertEqual(match_ocr_candidates(body, 'Save')['status'], 'not_found')
        self.assertEqual(match_ocr_candidates(body, 'Save', 'fuzzy', min_score=75)['top']['score'], 75)
        self.assertEqual(match_ocr_candidates(body, 'Save', 'fuzzy', min_score=76)['status'], 'not_found')

    def test_source_incomplete_preserved(self):
        result = match_ocr_candidates({'ocr': {'words': [word('Save')]}, 'status': 'partial'}, 'Save')
        self.assertTrue(result['source_incomplete'])
        self.assertEqual(result['status'], 'partial')

    def test_invalid_geometry_and_budgets_rejected(self):
        for args in ({'limit': 0}, {'min_score': True}, {'ambiguity_margin': 0}):
            with self.assertRaises(ValueError): match_ocr_candidates({}, 'x', **args)
        for w in (word('Save', x=math.nan), word('Save', width=0), word('Save', x=True)):
            with self.assertRaises(ValueError): match_ocr_candidates({'words': [w]}, 'Save')
        with self.assertRaises(ValueError): match_ocr_candidates({'words': [word('x')] * 10_001}, 'x')
        with self.assertRaises(ValueError): normalize_ocr_text('x' * 4097)
        with self.assertRaises(ValueError): score_ocr_text('a' * 4096, 'b' * 4096, 'fuzzy')
        with self.assertRaises(ValueError): match_ocr_candidates({'coordinate_space': 'screen_pixels'}, 'Save')


class FusionTests(unittest.TestCase):
    def setUp(self):
        self.target = {'hwnd': '0x20', 'pid': 42}
        self.geometry = {'x': -200, 'y': -100, 'width': 200, 'height': 100, 'image_width': 100, 'image_height': 50}
        self.candidates = match_ocr_candidates({'words': [word('Save', 10, 10, 20, 10)]}, 'Save')['candidates']
        self.button = {'name': 'Save', 'control_type': 'Button', 'process_id': 42, 'element_ref': 'opaque-reference',
                       'patterns': ['Invoke'], 'is_enabled': True, 'is_offscreen': False,
                       'bounding_rectangle': {'x': -190, 'y': -90, 'width': 70, 'height': 50}, 'children': []}

    def fuse(self, nodes=None, **kwargs):
        params = dict(geometry=self.geometry, target=self.target, uia_target=self.target)
        params.update(kwargs)
        return fuse_ocr_uia(self.candidates, nodes if nodes is not None else [self.button], **params)

    def test_explicit_image_to_physical_mapping_and_reference(self):
        result = self.fuse()
        self.assertEqual(result['top']['point'], {'x': -160, 'y': -70, 'screen_x': -160, 'screen_y': -70,
                                               'image_x': 20, 'image_y': 15, 'coordinate_space': 'physical_screen_pixels'})
        self.assertEqual(result['top']['uia']['element_ref'], 'opaque-reference')
        self.assertEqual(result['coordinate_space'], 'physical_screen_pixels')
        self.assertTrue(result['top']['can_invoke'])
        self.assertFalse(result['top']['actionable'])
        self.assertFalse(result['actionable'])

    def test_mismatched_or_missing_identity_refused(self):
        for target in ({'hwnd': '0x21', 'pid': 42}, {'hwnd': '0x20', 'pid': 43}, {'hwnd': '0x20'}, {'hwnd': '', 'pid': 42}):
            with self.assertRaises(ValueError): self.fuse(uia_target=target)
        self.assertEqual(self.fuse(uia_target={'hwnd': 32, 'pid': 42})['status'], 'ok')

    def test_missing_mapping_and_outside_ocr_refused(self):
        with self.assertRaises(ValueError): self.fuse(geometry={'x': 0, 'y': 0, 'width': 1, 'height': 1})
        self.candidates[0]['x'] = -1
        with self.assertRaises(ValueError): self.fuse()

    def test_center_comes_from_rect_not_untrusted_cx(self):
        self.candidates[0].update(cx=999999, cy=999999)
        self.assertEqual(self.fuse()['top']['point']['screen_x'], -160)

    def test_parent_climb_to_pattern(self):
        self.button['children'] = [{'name': 'label', 'patterns': [],
                                    'bounding_rectangle': {'x': -175, 'y': -80, 'width': 30, 'height': 20}}]
        result = self.fuse()
        self.assertEqual(result['top']['parent_climb_depth'], 1)
        self.assertEqual(result['top']['pattern'], 'InvokePattern')
        self.assertEqual(result['candidate_count'], 2)

    def test_equal_overlapping_uia_candidates_are_ambiguous(self):
        second = dict(self.button, name='Other', element_ref='second-reference')
        result = self.fuse([self.button, second], limit=1)
        self.assertTrue(result['ambiguous'])
        self.assertEqual(result['candidate_count'], 2)
        self.assertEqual(result['status'], 'partial')

    def test_different_process_excluded(self):
        self.button['process_id'] = 7
        self.assertEqual(self.fuse()['status'], 'not_found')

    def test_cycle_and_invalid_rectangle_rejected(self):
        self.button['children'] = [self.button]
        with self.assertRaises(ValueError): self.fuse()
        self.button['children'] = []
        self.button['bounding_rectangle']['x'] = float('inf')
        with self.assertRaises(ValueError): self.fuse()

    def test_disabled_offscreen_evidence_never_actions(self):
        self.button.update(is_enabled=False, is_offscreen=True)
        result = self.fuse()
        self.assertFalse(result['actionable'])
        self.assertFalse(result['top']['enabled'])
        self.assertTrue(result['top']['offscreen'])
        self.assertEqual(result['top']['fusion_score'], 170)

    def test_source_ambiguity_and_truncation_preserved(self):
        candidates = {'candidates': self.candidates, 'ambiguous': True, 'truncated': True}
        result = fuse_ocr_uia(candidates, [self.button], geometry=self.geometry, target=self.target, uia_target=self.target)
        self.assertTrue(result['ambiguous'])
        self.assertTrue(result['truncated'])


class PngAndDiffTests(unittest.TestCase):
    def test_all_png_filters_rgba(self):
        pixels = bytes((i * 37) % 256 for i in range(3 * 5 * 4))
        result = decode_png(png(3, 5, filters=[0, 1, 2, 3, 4], pixels=pixels))
        self.assertEqual(result, {'width': 3, 'height': 5, 'rgba': pixels})

    def test_rgb_expansion_and_split_idat(self):
        encoded = png(channels=3, filters=[1, 4])
        decoded = decode_png(encoded)
        source = bytes((i * 31 + 7) % 256 for i in range(12))
        expected = b''.join(source[i:i + 3] + b'\xff' for i in range(0, 12, 3))
        self.assertEqual(decoded['rgba'], expected)
        length = struct.unpack_from('>I', encoded, 33)[0]
        compressed = encoded[41:41 + length]
        split = encoded[:33] + chunk(b'IDAT', compressed[:2]) + chunk(b'IDAT', compressed[2:]) + chunk(b'IEND', b'')
        self.assertEqual(decode_png(split), decoded)

    def test_crc_truncation_and_trailing_bytes_rejected(self):
        encoded = png()
        corrupt = bytearray(encoded)
        corrupt[45] ^= 1
        for data in (bytes(corrupt), encoded[:-1], encoded + b'extra', b'notpng'):
            with self.subTest(data=data[:8]), self.assertRaises(ValueError): decode_png(data)

    def test_unsupported_header_and_huge_dimensions_rejected(self):
        for width, height, depth, color, interlace in ((10001, 1, 8, 6, 0), (5000, 5000, 8, 6, 0), (1, 1, 16, 6, 0), (1, 1, 8, 3, 0), (1, 1, 8, 6, 1)):
            header = struct.pack('>IIBBBBB', width, height, depth, color, 0, 0, interlace)
            encoded = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(b'\0\0\0\0\0')) + chunk(b'IEND', b'')
            with self.assertRaises(ValueError): decode_png(encoded)

    def test_deflate_overrun_invalid_filter_and_extra_stream_rejected(self):
        prefix = png(1, 1)[:33]
        for raw in (b'\0' * 100000, b'\5\0\0\0\0', b'\0'):
            encoded = prefix + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')
            with self.assertRaises(ValueError): decode_png(encoded)
        encoded = prefix + chunk(b'IDAT', zlib.compress(b'\0' * 5) + zlib.compress(b'\0' * 5)) + chunk(b'IEND', b'')
        with self.assertRaises(ValueError): decode_png(encoded)

    def test_rgb_l1_threshold_strict_and_alpha_ignored(self):
        before = {'width': 2, 'height': 1, 'rgba': bytes([0, 0, 0, 0, 0, 0, 0, 0])}
        after = {'width': 2, 'height': 1, 'rgba': bytes([8, 8, 0, 255, 8, 8, 1, 255])}
        result = screenshot_diff(before, after, threshold=16)
        self.assertEqual(result['changed_pixels'], 1)
        self.assertEqual(result['changed_ratio'], .5)
        self.assertTrue(result['changed'])
        self.assertFalse(result['alpha_compared'])

    def test_png_bytes_accepted_and_no_change(self):
        result = screenshot_diff(png(), png())
        self.assertEqual(result['changed_pixels'], 0)
        self.assertFalse(result['changed'])
        self.assertEqual(result['status'], 'ok')

    def test_region_offset_and_overlapping_masks_count_once(self):
        before = {'width': 4, 'height': 3, 'rgba': b'\0\0\0\xff' * 12}
        after = {'width': 4, 'height': 3, 'rgba': b'\xff\0\0\xff' * 12}
        result = screenshot_diff(before, after, region={'x': 1, 'y': 1, 'width': 3, 'height': 2},
                                 ignore_regions=[{'x': 0, 'y': 0, 'w': 3, 'h': 3}, {'x': 2, 'y': 1, 'w': 1, 'h': 2}])
        self.assertEqual(result['offset'], {'x': 1, 'y': 1})
        self.assertEqual(result['total_pixels'], 6)
        self.assertEqual(result['ignored_pixels'], 4)
        self.assertEqual(result['effective_pixels'], 2)
        self.assertEqual(result['changed_pixels'], 2)

    def test_all_masked_is_inconclusive(self):
        result = screenshot_diff(png(), png(), ignore_regions=[{'x': 0, 'y': 0, 'width': 2, 'height': 2}])
        self.assertEqual(result['status'], 'partial')
        self.assertFalse(result['comparison_complete'])
        self.assertEqual(result['effective_pixels'], 0)

    def test_different_sizes_intersection_marked_partial(self):
        result = screenshot_diff(png(2, 2), png(1, 1))
        self.assertEqual(result['total_pixels'], 1)
        self.assertEqual(result['status'], 'partial')
        self.assertFalse(result['same_dimensions'])

    def test_empty_region_invalid_buffers_and_limits(self):
        with self.assertRaises(ValueError): screenshot_diff(png(), png(), region={'x': 5, 'y': 5, 'width': 1, 'height': 1})
        with self.assertRaises(ValueError): screenshot_diff(png(), png(), threshold=766)
        with self.assertRaises(ValueError): screenshot_diff({'width': 1, 'height': 1, 'rgba': b'bad'}, png())
        with self.assertRaises(ValueError): screenshot_diff(png(), png(), ignore_regions=[{}] * 65)
        with self.assertRaises(ValueError): screenshot_diff(png(), png(), region={'x': .5, 'y': 0, 'width': 1, 'height': 1})


if __name__ == '__main__':
    unittest.main()
