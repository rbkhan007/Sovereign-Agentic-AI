import os
import re
import time
import logging
import threading
from collections import defaultdict
from typing import List, Dict, Set, Optional

logger = logging.getLogger(__name__)

# Obsidian-style wiki-link patterns
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|([^\]]+?))?\]\]")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_TAG_RE = re.compile(r"(?<![a-zA-Z0-9#:/\-_=.])#([A-Za-z0-9_\-/]+)", re.MULTILINE)


class KnowledgeGraph:
    """In-memory Obsidian-like knowledge graph with wiki-links, tags, and backlinks.

    Stores document relationships as a directed graph. Each node is a document
    (identified by workspace_id + filename). Edges are wiki-links. Tags are
    extracted from ``#tag`` syntax and stored per-document for filtering.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # workspace_id -> {filename -> {content, links, backlinks, tags, headings}}
        self._docs: Dict[str, Dict[str, dict]] = defaultdict(dict)
        # workspace_id -> {filename -> set of linked filenames}
        self._links: Dict[str, Dict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))
        # workspace_id -> {filename -> set of backlinked filenames}
        self._backlinks: Dict[str, Dict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))
        # workspace_id -> {filename -> set of tags}
        self._tags: Dict[str, Dict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))
        # workspace_id -> {tag -> set of filenames}
        self._tag_index: Dict[str, Dict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))
        # workspace_id -> {filename -> list of headings}
        self._headings: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))

    def parse_document(self, workspace_id: str, filename: str, content: str) -> dict:
        """Parse a markdown document for wiki-links, tags, and headings.

        Returns a summary dict with links, tags, headings found.
        """
        stripped = _strip_code_blocks(content)
        links = _extract_wikilinks(stripped)
        tags = _extract_tags(stripped)
        headings = _extract_headings(stripped)

        with self._lock:
            old_links = self._links[workspace_id].get(filename, set())
            old_tags = self._tags[workspace_id].get(filename, set())

            # Remove old backlinks
            for old_target in old_links:
                self._backlinks[workspace_id][old_target].discard(filename)

            # Update links
            self._links[workspace_id][filename] = links
            self._tags[workspace_id][filename] = tags
            self._headings[workspace_id][filename] = headings
            self._docs[workspace_id][filename] = {
                "content": content,
                "links": links,
                "tags": tags,
                "headings": headings,
                "added_at": time.time(),
            }

            # Add new backlinks
            for target in links:
                self._backlinks[workspace_id][target].add(filename)

            # Update tag index
            for old_tag in old_tags:
                self._tag_index[workspace_id][old_tag].discard(filename)
            for tag in tags:
                self._tag_index[workspace_id][tag].add(filename)

        return {
            "links": sorted(links),
            "tags": sorted(tags),
            "headings": headings,
            "backlinks_to": sorted(self._backlinks[workspace_id].get(filename, set())),
        }

    def remove_document(self, workspace_id: str, filename: str) -> None:
        """Remove a document from the graph and clean up all references."""
        with self._lock:
            links = self._links[workspace_id].pop(filename, set())
            tags = self._tags[workspace_id].pop(filename, set())
            self._headings[workspace_id].pop(filename, None)
            self._docs[workspace_id].pop(filename, None)

            for target in links:
                self._backlinks[workspace_id][target].discard(filename)
            for tag in tags:
                self._tag_index[workspace_id][tag].discard(filename)

    def get_backlinks(self, workspace_id: str, filename: str) -> Set[str]:
        """Get all documents that link to this document."""
        with self._lock:
            return set(self._backlinks[workspace_id].get(filename, set()))

    def get_files_by_tag(self, workspace_id: str, tag: str) -> Set[str]:
        """Get all files that contain a specific tag."""
        with self._lock:
            return set(self._tag_index[workspace_id].get(tag, set()))

    def get_all_tags(self, workspace_id: str) -> Dict[str, int]:
        """Get all tags in a workspace with their file counts."""
        with self._lock:
            return {tag: len(files) for tag, files in self._tag_index[workspace_id].items()
                    if files}

    def get_graph(self, workspace_id: str) -> dict:
        """Return the full knowledge graph for a workspace.

        Returns nodes (files with metadata) and edges (links between files).
        Link targets are resolved to full filenames where a match exists, so
        in_degree/out_degree and edges all reference real node ids.
        """
        with self._lock:
            files = self._links.get(workspace_id, {})
            tags_map = self._tags.get(workspace_id, {})
            headings_map = self._headings.get(workspace_id, {})

            base_to_file = {}
            for f in files:
                base_to_file[os.path.splitext(f)[0]] = f
                base_to_file[f] = f

            nodes = []
            edges = []
            for filename in files:
                tags = sorted(tags_map.get(filename, set()))
                headings = headings_map.get(filename, [])
                base = os.path.splitext(filename)[0]
                in_degree = 0
                for targets in files.values():
                    if filename in targets or base in targets:
                        in_degree += 1
                nodes.append({
                    "id": filename,
                    "tags": tags,
                    "headings": headings[:10],
                    "out_degree": len(files[filename]),
                    "in_degree": in_degree,
                })
                for target in files[filename]:
                    edges.append({"source": filename, "target": base_to_file.get(target, target)})

            return {
                "workspace_id": workspace_id,
                "nodes": nodes,
                "edges": edges,
                "node_count": len(nodes),
                "edge_count": len(edges),
            }

    def resolve_link(self, workspace_id: str, filename: str, heading: Optional[str] = None) -> Optional[dict]:
        """Resolve a wiki-link to its target document content.

        If heading is provided, returns content starting from that heading.
        """
        with self._lock:
            doc = self._docs.get(workspace_id, {}).get(filename)
            if not doc:
                return None
            content = doc["content"]
            if heading:
                pattern = re.compile(
                    rf"^##{{0,6}}\s+{re.escape(heading)}\s*$",
                    re.MULTILINE | re.IGNORECASE,
                )
                match = pattern.search(content)
                if match:
                    start = match.start()
                    next_heading = re.search(r"^#{1,6}\s+", content[match.end():], re.MULTILINE)
                    end = match.end() + next_heading.start() if next_heading else len(content)
                    content = content[start:end]
            return {
                "filename": filename,
                "content": content,
                "tags": sorted(doc.get("tags", set())),
                "headings": doc.get("headings", []),
            }

    def search_by_tag(self, workspace_id: str, tag: str) -> List[dict]:
        """Search for all documents with a specific tag."""
        files = self.get_files_by_tag(workspace_id, tag)
        results = []
        with self._lock:
            for filename in sorted(files):
                doc = self._docs.get(workspace_id, {}).get(filename, {})
                results.append({
                    "filename": filename,
                    "tags": sorted(doc.get("tags", set())),
                    "headings": doc.get("headings", [])[:5],
                    "preview": (doc.get("content", "")[:200] if doc else ""),
                })
        return results

    def orphans(self, workspace_id: str) -> List[str]:
        """Find documents with no incoming or outgoing links."""
        with self._lock:
            files = set(self._links.get(workspace_id, {}).keys())
            backlinked = set()
            for targets in self._backlinks.get(workspace_id, {}).values():
                backlinked.update(targets)
            all_files = files | backlinked
            orphans = []
            for f in sorted(all_files):
                if not self._links[workspace_id].get(f) and not self._backlinks[workspace_id].get(f):
                    orphans.append(f)
            return orphans

    def recent(self, workspace_id: str, limit: int = 10) -> List[dict]:
        """Get recently added documents (most recently parsed first)."""
        with self._lock:
            docs = self._docs.get(workspace_id, {})
            files = sorted(
                docs.keys(),
                key=lambda fn: docs[fn].get("added_at", 0.0),
                reverse=True,
            )[:limit]
            result = []
            for filename in files:
                doc = docs[filename]
                result.append({
                    "filename": filename,
                    "tags": sorted(doc.get("tags", set())),
                    "headings": doc.get("headings", [])[:3],
                })
            return result


def _strip_code_blocks(text: str) -> str:
    """Remove fenced and inline code blocks so links/tags inside code are ignored."""
    text = _FENCED_CODE_RE.sub("", text)
    text = _INLINE_CODE_RE.sub("", text)
    return text


def _extract_wikilinks(text: str) -> Set[str]:
    """Extract all [[wiki-link]] targets from text."""
    links = set()
    for m in _WIKILINK_RE.finditer(text):
        target = m.group(1).strip()
        if target:
            links.add(target)
    return links


def _extract_tags(text: str) -> Set[str]:
    """Extract all #tags from text."""
    tags = set()
    for m in _TAG_RE.finditer(text):
        tag = m.group(1).strip()
        if tag:
            tags.add(tag)
    return tags


def _extract_headings(text: str) -> List[str]:
    """Extract all markdown headings from text."""
    headings = []
    for m in _HEADING_RE.finditer(text):
        heading = m.group(2).strip()
        if heading:
            headings.append(heading)
    return headings


# Singleton instance
knowledge_graph = KnowledgeGraph()
