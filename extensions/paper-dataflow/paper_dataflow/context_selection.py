"""Budgeted extractive selection: lexical facility location + role coverage.

Reference-only adaptation of coverage/diversity selection, not a reproduction
of an embedding-based paper or a claim of state-of-the-art SFT quality. All
scores are deterministic proxies; unchanged source blocks remain authoritative.
"""
import math
import re
from collections import Counter

import numpy as np


VERSION = 'lexical-facility-role-v1'
ROLES = {
    'overview': r'abstract|introduction|conclusion|摘要|结论',
    'method': r'method|approach|algorithm|framework|data|training|方法|算法|数据',
    'experiment': r'experiment|evaluation|result|ablation|analysis|实验|结果|消融',
    'boundary': r'limitation|discussion|failure|局限|讨论|失败',
}
EXCLUDE = r'references|bibliography|acknowledg|参考文献|致谢'
STOP = set('the a an of to in and or for is are with on as by this that we our from be it at'.split())


def _terms(text):
    return Counter(t for t in re.findall(r'[a-z][a-z0-9_-]{2,}|[\u4e00-\u9fff]{1,2}', text.lower())
                   if t not in STOP)


def propose_contexts(df, max_contexts=None):
    """Return document->IDs and auditable offline selection traces.

    Optimize F(S)=mean_j max_i∈S cosine(tfidf_j,tfidf_i)
    +0.5*|union roles(S)|/|available roles|. Both terms have diminishing
    returns. Greedy ranks all available contexts by default; an optional
    cardinality cap is for offline comparisons only. No measured semantic
    coverage, generation quality, or speed-up is implied by this objective.
    Exact normalized duplicates add zero gain and are not selected twice.
    """
    if max_contexts is not None and (type(max_contexts) is not int or max_contexts < 1):
        raise ValueError('max_contexts must be a positive integer')
    groups = {}
    seen = set()
    for row in df.to_dict('records'):
        key = (row['document_id'], row['unit_id'])
        if key in seen:
            raise ValueError('Duplicate document/context identity')
        seen.add(key)
        groups.setdefault(row['document_id'], []).append(row)
    selections, traces = {}, {}
    for doc, rows in groups.items():
        eligible, rejected, fingerprints = [], [], set()
        for row in sorted(rows, key=lambda r: r['unit_id']):
            title = row.get('chunk_metadata', {}).get('section_title', '')
            fingerprint = ' '.join(row['context'].lower().split())
            # Use raw text for duplicate identity; context prefixes contain IDs.
            fingerprint = ' '.join(row.get('raw_chunk', fingerprint).lower().split())
            reason = ('originally_ineligible' if not row.get('context_valid') else
                      'non_content_section' if re.search(EXCLUDE, title, re.I) else
                      'short_frontmatter' if row.get('context_tokens', 0) < 150 else
                      'exact_duplicate' if fingerprint in fingerprints else '')
            if reason:
                rejected.append({'unit_id': row['unit_id'], 'reason': reason})
                continue
            fingerprints.add(fingerprint)
            roles = {name for name, pattern in ROLES.items() if re.search(pattern, title, re.I)}
            eligible.append((row, _terms(row.get('raw_chunk', row['context'])), roles))
        if not eligible:
            raise ValueError('No eligible substantive context for paper ' + doc)
        n = len(eligible)
        frequency = Counter(t for _, terms, _ in eligible for t in terms)
        vocab = sorted(frequency)
        vectors = np.array([[(1 + math.log(terms[t])) * (1 + math.log((n + 1)/(frequency[t] + 1)))
                             if terms[t] else 0 for t in vocab] for _, terms, _ in eligible])
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / np.maximum(norms, 1e-12)
        similarity = np.clip(vectors @ vectors.T, 0, 1)
        available_roles = set().union(*(roles for _, _, roles in eligible))
        covered = np.zeros(n)
        roles, chosen, steps = set(), [], []
        for _ in range(n if max_contexts is None else min(max_contexts, n)):
            gains = []
            for i, (_, _, item_roles) in enumerate(eligible):
                if i in chosen:
                    continue
                coverage_gain = float(np.maximum(covered, similarity[:, i]).mean() - covered.mean())
                role_gain = len(item_roles - roles) / max(1, len(available_roles))
                gains.append((coverage_gain + 0.5 * role_gain, i, coverage_gain, role_gain))
            gain, i, coverage_gain, role_gain = max(gains, key=lambda g: (g[0], -g[1]))
            if gain <= 1e-10:
                break
            row, _, item_roles = eligible[i]
            chosen.append(i)
            covered = np.maximum(covered, similarity[:, i])
            roles |= item_roles
            steps.append(dict(unit_id=row['unit_id'], section=row.get('chunk_metadata', {}).get('section_title', ''),
                              roles=sorted(item_roles), marginal_gain=gain,
                              lexical_coverage_gain=coverage_gain, role_coverage_gain=role_gain,
                              context_tokens=row.get('context_tokens'), source_map=row.get('source_map')))
        selections[doc] = [eligible[i][0]['unit_id'] for i in chosen]
        traces[doc] = dict(algorithm=VERSION, representation='within-paper word TF-IDF; no embeddings',
                           input_contexts=len(rows), eligible_contexts=n, steps=steps,
                           lexical_facility_score=float(covered.mean()),
                           covered_roles=sorted(roles), available_roles=sorted(available_roles), excluded=rejected)
    return selections, traces


def budget_contexts(df, allocations, max_candidates_per_paper=8):
    """Apply a planner's variable sample allocations, independently of ranking.

    Ranking does not assign sample counts or impose a fixed number of contexts.
    The caller supplies allocations from a paper-level plan.
    """
    from paper_dataflow.low_cost_sft import select_paper_contexts
    return select_paper_contexts(df, allocations, max_candidates_per_paper)
