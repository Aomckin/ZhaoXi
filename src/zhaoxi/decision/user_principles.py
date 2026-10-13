"""Writable summary indexes; user archive originals remain the primary evidence."""
import logging
import json
import hashlib
import os
import tempfile
import threading
from datetime import UTC, datetime
from .history import append_row, read_rows
import re
from pathlib import Path
from .learning_models import UserPrinciple, require_owner
from .principles import relevance


class UserPrincipleStore:
    def __init__(self, directory, archive=None):
        self.archive = archive
        self.directory = Path(directory)
        self._lock = threading.RLock()

    def list(self, *, verify_sources=True):
        require_owner()
        rows = []
        for path in sorted(self.directory.glob('*.json'))[:200]:
            if path.resolve().parent != self.directory.resolve():
                continue
            try:
                row = UserPrinciple.model_validate_json(path.read_text(encoding='utf-8-sig'))
                if row.id == path.stem:
                    rows.append(row.model_dump(mode='json'))
            except ValueError:
                logging.getLogger('DECISION').warning('invalid user principle index')
        indexed = {row['id']: row for row in rows}
        for event in read_rows(self.directory / 'revisions.jsonl'):
            try:
                row = UserPrinciple.model_validate(event.get('after')).model_dump(mode='json')
                indexed[row['id']] = row
            except ValueError:
                logging.getLogger('DECISION').warning('invalid principle revision')
        rows = list(indexed.values())
        if self.archive and verify_sources:
            for row in rows:
                row["source_status"] = self.archive.source_status(row)
                row["effective_status"] = ("retired" if row["status"] != "active" else
                                           "active" if row["source_status"] == "current" else "needs_update")
        return rows

    def save(self, values, *, actor):
        require_owner()
        row = UserPrinciple.model_validate(values).model_dump(mode='json')
        with self._lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / (row['id'] + '.json')
            if path.resolve().parent != self.directory.resolve():
                raise ValueError('准则路径超出索引目录。')
            before = next((r for r in self.list(verify_sources=False) if r['id'] == row['id']), None)
            if before and {k: v for k, v in before.items() if k not in {'updated_at', 'source_status', 'effective_status'}} == {k: v for k, v in row.items() if k != 'updated_at'}:
                return before
            append_row(self.directory / 'revisions.jsonl', {
                'timestamp': datetime.now(UTC).isoformat(), 'actor': actor, 'before': before, 'after': row})
            # Revisions are authoritative; this per-entry file is a repairable index.
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.directory, delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(json.dumps(row, ensure_ascii=False, indent=2) + '\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            except OSError:
                logging.getLogger('DECISION').warning('principle index write failed; committed revision retained')
            finally:
                if temporary is not None:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        logging.getLogger('DECISION').warning('principle temporary index cleanup failed')
            return row

    def revisions(self, identity):
        require_owner()
        return [r for r in read_rows(self.directory / 'revisions.jsonl') if r['after']['id'] == identity]

    def synchronize(self):
        """Index declared user principles/protocols without inventing new rules."""
        require_owner()
        if self.archive is None:
            return 0
        existing = {row['id']: row for row in self.list(verify_sources=False)}
        changed = 0
        for relative in self.archive.available_paths():
            if not relative.startswith('user/'):
                continue
            path = (self.archive.directory / relative).resolve()
            if not path.is_relative_to(self.archive.directory / 'user') or not path.is_file():
                continue
            text = path.read_text(encoding='utf-8-sig')[:32000]
            lines = text.splitlines()
            title = next((line[2:].strip() for line in lines if line.startswith('# ')), '')
            if not any(word in title for word in ('准则', '协议')):
                continue
            hierarchy = []
            for number, line in enumerate(lines, 1):
                heading = re.match(r'^(#{1,6})\s+(.+)', line)
                if not heading:
                    continue
                level, label = len(heading[1]), heading[2].strip()
                hierarchy = [(depth, name) for depth, name in hierarchy if depth < level]
                hierarchy.append((level, label))
                if label == title:
                    continue
                section = ' / '.join(name for _, name in hierarchy if name != title)
                identity = 'up-archive-' + hashlib.sha256((relative + '\0' + section).encode()).hexdigest()[:24]
                before = existing.get(identity)
                if before and (before['status'] != 'active' or before['origin'] != 'zhaoxi_summary' or 'archive_index' not in before['tags']):
                    continue  # Owner revisions remain authoritative over automatic indexes.
                values = {'id': identity, 'statement': title + ' · ' + section,
                    'domain': 'general', 'tags': ['archive_index', title], 'origin': 'zhaoxi_summary',
                    'confidence': .7, 'status': 'active',
                    'source': self.archive.evidence(f'archive:{relative}:L{number}', line),
                    'updated_at': datetime.now(UTC).isoformat()}
                if before and all(before.get(key) == value for key, value in values.items() if key != 'updated_at'):
                    continue
                self.save(values, actor='zhaoxi_summary')
                changed += 1
        return changed

    def retrieve(self, query, limit=5):
        self.synchronize()
        rows = [(relevance(query, ' '.join([r['statement'], r['domain'], *r['tags']])), r)
                for r in self.list() if r['status'] == 'active' and r.get('source_status', 'current') == 'current']
        rows.sort(key=lambda x: -x[0])
        return [r for score, r in rows if score][:limit]


class DecisionPrincipleArchiveProvider:
    def __init__(self, directory, paths):
        self.directory = Path(directory).resolve()
        self.paths = tuple(paths)

    def available_paths(self):
        require_owner()
        user = self.directory / 'user'
        discovered = sorted(p.relative_to(self.directory).as_posix() for p in user.rglob('*')
                            if p.suffix.lower() in {'.md', '.txt'} and p.is_file()
                            and p.resolve().is_relative_to(user.resolve()) and p.resolve().is_relative_to(self.directory)) if user.is_dir() else []
        return tuple(dict.fromkeys([*discovered[:200], *self.paths[:20]]))

    def fragments(self, query, limit=5, *, user_only=False):
        require_owner()
        matches = []
        for relative in self.available_paths():
            if user_only and not relative.replace("\\", "/").startswith("user/"):
                continue
            path = (self.directory / relative).resolve()
            if not path.is_relative_to(self.directory) or path.suffix.lower() not in {'.md', '.txt'} or not path.is_file():
                continue
            relative = path.relative_to(self.directory).as_posix()
            if user_only and not relative.startswith('user/'):
                continue
            with path.open(encoding='utf-8-sig') as stream:
                text = stream.read(32000)
            lines = text.splitlines()
            for start in range(0, len(lines), 8):
                fragment = '\n'.join(lines[start:start + 8])[:1000]
                score = relevance(query, fragment + " " + relative)
                if score:
                    matches.append((score, {'ref': f'archive:{relative}:L{start + 1}',
                        'path': relative, 'line': start + 1, 'content': fragment,
                        'authority': 'user_archive' if relative.replace('\\', '/').startswith('user/') else 'agent_authored_archive',
                        'source': {'type': 'archive', 'path': str(path),
                                   'modified_at': path.stat().st_mtime}}))
        matches.sort(key=lambda x: (x[1]['authority'] != 'user_archive', -x[0]))
        return [r for _, r in matches[:min(limit, 8)]]

    def source_fragment(self, principle):
        require_owner()
        source = principle['source']
        source_path = source.get('path', '').replace('\\', '/')
        relative = source_path if source_path.startswith('user/') else next((p for p in self.available_paths() if source_path == p or source_path.endswith('/' + p)), None)
        if relative is None:
            return []
        path = (self.directory / relative).resolve()
        if relative.startswith('user/') and not path.is_relative_to(self.directory / 'user'):
            return []
        if not path.is_relative_to(self.directory) or not path.is_file() or path.suffix.lower() not in {'.md', '.txt'}:
            return []
        with path.open(encoding='utf-8-sig') as stream:
            lines = stream.read(32000).splitlines()
        match = re.fullmatch(r'archive:(.+):L(\d+)', source.get('ref', ''))
        if match:
            if match[1] != relative:
                return []
            start = int(match[2]) - 1
            if start < 0 or start >= len(lines):
                return []
            return [{'ref': source['ref'], 'path': relative, 'line': start + 1,
                     'content': '\n'.join(lines[start:start + 8])[:1000],
                     'authority': 'user_archive' if relative.startswith('user/') else 'agent_authored_archive',
                     'source': source}]
        section = source.get('ref', '').split('/')[-1].split('-')[0]
        start = next((i for i, line in enumerate(lines)
                      if re.match(r'^#+\s+' + re.escape(section) + r'(?:[\s.：:·]|$)', line)), None)
        if start is None:
            return []
        heading = len(lines[start]) - len(lines[start].lstrip('#'))
        end = next((i for i in range(start + 1, len(lines)) if
                    re.match(r'^#{1,' + str(heading) + r'}\s', lines[i])), min(len(lines), start + 40))
        return [{'ref': f'archive:{relative}:L{start + 1}', 'path': relative, 'line': start + 1,
                 'content': '\n'.join(lines[start:end])[:1200],
                 'authority': 'user_archive' if relative.startswith('user/') else 'agent_authored_archive',
                 'source': source}]

    def evidence(self, reference, quote):
        require_owner()
        match = re.fullmatch(r'archive:(user/.+):L(\d+)', reference)
        if not match:
            raise ValueError('须引用 archive/user 中实际存在的原文片段。')
        path = (self.directory / match[1]).resolve()
        if (not path.is_relative_to((self.directory / 'user').resolve()) or not path.is_relative_to(self.directory)
                or path.suffix.lower() not in {'.md', '.txt'} or not path.is_file()):
            raise ValueError('原文路径越界。')
        with path.open(encoding='utf-8-sig') as stream:
            text = stream.read(32000)
        lines = text.splitlines()
        start = int(match[2]) - 1
        fragment = '\n'.join(lines[start:start + 8])[:1000] if 0 <= start < len(lines) else ''
        if not quote.strip() or quote not in fragment:
            raise ValueError('引文不在指定原文片段内，请重新读取资料。')
        return {'type': 'archive', 'path': match[1], 'ref': reference, 'quote': quote,
                'sha256': hashlib.sha256(text.encode()).hexdigest()}

    def source_status(self, principle):
        source = principle['source']
        fragments = self.source_fragment(principle)
        if not fragments:
            return 'missing'
        if source.get('sha256'):
            try:
                current = self.evidence(source['ref'], source['quote'])
                if current['sha256'] != source['sha256']:
                    return 'changed'
            except (ValueError, OSError):
                return 'changed'
        return 'current'

    async def retrieve(self, query, *, limit=5):
        return self.fragments(query, limit)
