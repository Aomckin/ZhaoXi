"""Read-only explicit principle index and whitelisted archive fragments."""
import logging
import re
from pathlib import Path
from .learning_models import UserPrinciple, require_owner
from .principles import relevance


class UserPrincipleStore:
    def __init__(self, directory):
        self.directory = Path(directory)

    def list(self):
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
        return rows

    def retrieve(self, query, limit=5):
        rows = [(relevance(query, ' '.join([r['statement'], r['domain'], *r['tags']])), r)
                for r in self.list() if r['status'] == 'active']
        rows.sort(key=lambda x: -x[0])
        return [r for score, r in rows if score][:limit]


class DecisionPrincipleArchiveProvider:
    def __init__(self, directory, paths):
        self.directory = Path(directory).resolve()
        self.paths = tuple(paths)

    def fragments(self, query, limit=5):
        require_owner()
        matches = []
        for relative in self.paths[:20]:
            path = (self.directory / relative).resolve()
            if not path.is_relative_to(self.directory) or path.suffix.lower() != '.md' or not path.is_file():
                continue
            with path.open(encoding='utf-8-sig') as stream:
                text = stream.read(32000)
            lines = text.splitlines()
            for start in range(0, len(lines), 8):
                fragment = '\n'.join(lines[start:start + 8])[:1000]
                score = relevance(query, fragment)
                if score:
                    matches.append((score, {'ref': f'archive:{relative}:L{start + 1}',
                        'path': relative, 'line': start + 1, 'content': fragment,
                        'authority': 'user_archive' if relative.replace('\\', '/').startswith('user/') else 'agent_authored_archive',
                        'source': {'type': 'archive', 'path': str(path),
                                   'modified_at': path.stat().st_mtime}}))
        matches.sort(key=lambda x: -x[0])
        return [r for _, r in matches[:min(limit, 8)]]

    def source_fragment(self, principle):
        require_owner()
        source = principle['source']
        source_path = source.get('path', '').replace('\\', '/')
        relative = next((p for p in self.paths if source_path == p or source_path.endswith('/' + p)), None)
        if relative is None:
            return []
        path = (self.directory / relative).resolve()
        if not path.is_relative_to(self.directory) or not path.is_file() or path.suffix.lower() != '.md':
            return []
        with path.open(encoding='utf-8-sig') as stream:
            lines = stream.read(32000).splitlines()
        section = source.get('ref', '').split('/')[-1].split('-')[0]
        start = next((i for i, line in enumerate(lines)
                      if re.match(r'^#+\s+' + re.escape(section) + r'(?:[\s.：:·]|$)', line)), None)
        if start is None:
            return self.fragments(principle['statement'], 1)
        heading = len(lines[start]) - len(lines[start].lstrip('#'))
        end = next((i for i in range(start + 1, len(lines)) if
                    re.match(r'^#{1,' + str(heading) + r'}\s', lines[i])), min(len(lines), start + 40))
        return [{'ref': f'archive:{relative}:L{start + 1}', 'path': relative, 'line': start + 1,
                 'content': '\n'.join(lines[start:end])[:1200],
                 'authority': 'user_archive' if relative.startswith('user/') else 'agent_authored_archive',
                 'source': source}]

    async def retrieve(self, query, *, limit=5):
        return self.fragments(query, limit)
