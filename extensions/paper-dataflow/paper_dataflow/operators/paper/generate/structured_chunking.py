"""Structure-first paper chunks, with Chonkie recursion only for long prose."""
import hashlib

import pandas as pd
from chonkie import RecursiveChunker, RecursiveLevel, RecursiveRules
from dataflow.core import OperatorABC
from dataflow.utils.registry import OPERATOR_REGISTRY
from dataflow.utils.storage import DataFlowStorage

from .preparation import PaperEvidenceChunker, read_input


@OPERATOR_REGISTRY.register()
class PaperStructuredChunker(OperatorABC):
    def __init__(self, tokenizer_path: str, chunk_size: int = 1024):
        super().__init__()
        self.counter = PaperEvidenceChunker(tokenizer_path, chunk_size, 0)
        self.chunk_size = chunk_size
        self.recursive = RecursiveChunker(
            tokenizer_or_token_counter=self.count,
            chunk_size=chunk_size,
            # Stop at sentence boundaries. An indivisible oversize sentence is
            # retained and flagged rather than split through words or inline math.
            rules=RecursiveRules(levels=[
                RecursiveLevel(delimiters=['\n\n']),
                RecursiveLevel(delimiters=['. ', '! ', '? ', '。', '！', '？']),
            ]),
            min_characters_per_chunk=1,
        )

    def count(self, text):
        return len(self.counter._encode(text)['input_ids'])

    @staticmethod
    def get_desc(lang: str = 'zh'):
        return ('按 MinerU 章节及完整块组织论文，超长正文调用 Chonkie 递归切分；保留跨页来源区间，超长表格和公式不截断。'
                if lang == 'zh' else 'Group MinerU sections and blocks; recursively split long prose with Chonkie; preserve cross-page provenance and atomic tables/equations.')

    def run(self, storage: DataFlowStorage, input_key: str = 'source_page',
            output_key: str = 'raw_chunk', output_meta_key: str = 'chunk_metadata'):
        frame = read_input(storage, input_key, output_key, output_meta_key)
        groups = {}
        for row in frame.to_dict('records'):
            groups.setdefault(row[input_key]['document_id'], []).append(row)
        output = []
        self.exclusions = []
        for document_id, rows in groups.items():
            rows.sort(key=lambda r: r[input_key]['page_number'])
            if len({r[input_key]['page_number'] for r in rows}) != len(rows):
                raise ValueError('Duplicate source page')
            pending, section, previous_page = [], '', None
            base = {k: v for k, v in rows[0].items() if k != input_key}

            def emit():
                nonlocal pending
                if not pending:
                    return
                text = '\n'.join(p['text'] for p in pending)
                segments, cursor = [], 0
                for p in pending:
                    segments.append({k: v for k, v in p.items() if k != 'text'} |
                                    {'chunk_char_start': cursor, 'chunk_char_end': cursor + len(p['text'])})
                    cursor += len(p['text']) + 1
                count = self.count(text)
                flags = sorted({flag for p in pending for flag in p['flags']})
                if count > self.chunk_size:
                    flags.append('oversize_preserved')
                if all(p['type'] in {'title', 'paragraph_title', 'heading'} for p in pending):
                    flags.append('heading_only')
                identity = document_id + ':' + repr([(s['page_number'], s['char_start'], s['char_end']) for s in segments]) + ':' + text
                meta = {'chunk_id': hashlib.sha256(identity.encode()).hexdigest(),
                        'document_id': document_id, 'page_numbers': sorted({s['page_number'] for s in segments}),
                        'source_segments': segments, 'section_title': section,
                        'token_count': count, 'chunk_size': self.chunk_size,
                        'chunk_overlap': 0, 'flags': flags, 'eligible_for_qa': not flags,
                        'tokenizer_files_sha256': self.counter.tokenizer_files,
                        'selection_policy': 'structure_first_recursive'}
                output.append({**base, output_key: text, output_meta_key: meta})
                pending = []

            for row in rows:
                page = row[input_key]
                number = page['page_number']
                if previous_page is not None and number != previous_page + 1:
                    emit()  # Never fabricate continuity across unparsed pages.
                    section = ''
                previous_page = number
                for block in page['blocks']:
                    kind, content = block['type'], block['content']
                    if not content.strip():
                        continue
                    if page['text'][block['char_start']:block['char_end']] != content:
                        raise ValueError('Block does not match page source')
                    if kind in {'header', 'footer', 'page_number'}:
                        self.exclusions.append({'document_id': document_id, 'page_number': number,
                                                'block_id': block['block_id'], 'reason': 'page_furniture'})
                        continue
                    if kind not in {'text', 'title', 'paragraph_title', 'heading', 'table', 'equation', 'display_formula', 'formula'}:
                        # Figures can interrupt a paragraph in the page layout.
                        # Skip their non-text evidence without breaking surrounding
                        # prose continuity; unknown block kinds remain barriers.
                        if kind not in {'image', 'figure', 'chart'}:
                            emit()
                        self.exclusions.append({'document_id': document_id, 'page_number': number,
                                                'block_id': block['block_id'], 'reason': 'not_text_only_evidence', 'type': kind})
                        continue
                    if kind in {'title', 'paragraph_title', 'heading'}:
                        emit()
                        section = content
                    pieces = [content]
                    if kind == 'text' and self.count(content) > self.chunk_size:
                        pieces = [c.text for c in self.recursive.chunk(content)]
                        if ''.join(pieces) != content:
                            raise ValueError('Recursive chunker changed or dropped source text')
                    offset = block['char_start']
                    for piece in pieces:
                        flags = []
                        # Known source-audit issue; retain it visibly, do not send
                        # malformed mathematics into either generation arm.
                        if '\\tilde { - }' in piece:
                            flags.append('formula_rendering_review')
                        if pending and self.count('\n'.join([p['text'] for p in pending] + [piece])) > self.chunk_size:
                            emit()
                        pending.append({'text': piece, 'page_number': number, 'block_id': block['block_id'],
                                        'type': kind, 'bbox': block['bbox'], 'char_start': offset,
                                        'char_end': offset + len(piece), 'flags': flags})
                        offset += len(piece)
                        if self.count(piece) > self.chunk_size:
                            emit()
            emit()
        if not output:
            raise ValueError('No text evidence after structural extraction')
        storage.write(pd.DataFrame(output))
        return [output_key, output_meta_key]
