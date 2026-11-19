"""Read and edit document-level RDF properties while retaining unrelated XML."""

from xml.dom import minidom
from xml.parsers.expat import ExpatError

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
XML = "http://www.w3.org/XML/1998/namespace"
DC = "http://purl.org/dc/elements/1.1/"
PDF = "http://ns.adobe.com/pdf/1.3/"
XMP = "http://ns.adobe.com/xap/1.0/"
PDFA = "http://www.aiim.org/pdfa/ns/id/"
PROFILES = ("1a", "1b", "2a", "2b", "2u", "3a", "3b", "3u", "4", "4e", "4f")

# PDF Info name, XMP namespace, qualified property name and optional RDF container.
FIELDS = {
    "Title": (DC, "dc:title", "Alt"),
    "Author": (DC, "dc:creator", "Seq"),
    "Subject": (DC, "dc:description", "Alt"),
    "Keywords": (PDF, "pdf:Keywords", ""),
    "Creator": (XMP, "xmp:CreatorTool", ""),
    "Producer": (PDF, "pdf:Producer", ""),
}


def _children(parent: minidom.Element, namespace: str, name: str) -> list[minidom.Element]:
    return [child for child in parent.childNodes if isinstance(child, minidom.Element)
            and child.namespaceURI == namespace and child.localName == name]


def _append(parent: minidom.Element, namespace: str, name: str) -> minidom.Element:
    document = parent.ownerDocument
    assert document is not None
    element = document.createElementNS(namespace, name)
    element.setAttribute("xmlns:" + name.split(":")[0], namespace)
    parent.appendChild(element)
    return element


def _title_text(node: minidom.Element) -> str:
    if any(isinstance(child, minidom.Element) for child in node.childNodes):
        raise ValueError("Edit this structured title in the XMP tab.")
    return "".join(child.data for child in node.childNodes if isinstance(child, minidom.Text))


class Packet:
    """Edit the main RDF subject. Local declarations preserve existing namespace prefixes."""

    def __init__(self, xml: str) -> None:
        if not xml:
            xml = (f'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="{RDF}">'
                   '<rdf:Description rdf:about=""/></rdf:RDF></x:xmpmeta>')
        try:
            self.dom = minidom.parseString(xml)
        except ExpatError as exc:
            raise ValueError(f"Invalid XMP XML: {exc}") from exc
        roots = self.dom.getElementsByTagNameNS(RDF, "RDF")
        if not roots:
            raise ValueError("XMP must contain an rdf:RDF element.")
        self.root = roots[0]
        self.subjects = [node for node in _children(self.root, RDF, "Description")
                         if not node.getAttributeNS(RDF, "about")]

    def subject(self) -> minidom.Element:
        """Return or create the description of the document itself."""
        if not self.subjects:
            node = _append(self.root, RDF, "rdf:Description")
            node.setAttributeNS(RDF, "rdf:about", "")
            self.subjects.append(node)
        return self.subjects[0]

    def _properties(self, namespace: str, local: str) -> list[minidom.Element | minidom.Attr]:
        result: list[minidom.Element | minidom.Attr] = []
        for subject in self.subjects:
            attr = subject.getAttributeNodeNS(namespace, local)
            if attr is not None:
                result.append(attr)
            result.extend(_children(subject, namespace, local))
        return result

    def has_title(self) -> bool:
        """Return whether the document has a dc:title property, including an empty array."""
        return bool(self._properties(DC, "title"))

    def titles(self) -> dict[str, str]:
        """Read language alternatives, also accepting older scalar title representations."""
        properties = self._properties(DC, "title")
        result: dict[str, str] = {}
        seen: set[str] = set()
        for prop in properties:
            if isinstance(prop, minidom.Attr):
                entries = [("x-default", prop.value)]
            else:
                groups = _children(prop, RDF, "Alt")
                if groups:
                    entries = [(item.getAttributeNS(XML, "lang"), _title_text(item))
                               for group in groups for item in _children(group, RDF, "li")]
                else:
                    entries = [(prop.getAttributeNS(XML, "lang") or "x-default", _title_text(prop))]
            for tag, title in entries:
                if not tag or tag.lower() in seen:
                    raise ValueError("Resolve missing or duplicate title language tags in the XMP tab.")
                seen.add(tag.lower())
                result["x-default" if tag.lower() == "x-default" else tag] = title
        return result

    def set_titles(self, titles: dict[str, str]) -> None:
        """Apply a language draft, keeping untouched alternatives and their RDF qualifiers."""
        props = self._properties(DC, "title")
        pending = {tag.lower(): (tag, value) for tag, value in titles.items()}
        target: minidom.Element | None = None
        for prop in props:
            groups = _children(prop, RDF, "Alt") if isinstance(prop, minidom.Element) else []
            if groups and titles:
                for group in groups:
                    if target is None:
                        target = group
                    for item in _children(group, RDF, "li"):
                        entry = pending.pop(item.getAttributeNS(XML, "lang").lower(), None)
                        if entry is None:
                            group.removeChild(item)
                        elif _title_text(item) != entry[1]:
                            for child in list(item.childNodes):
                                if isinstance(child, minidom.Text):
                                    item.removeChild(child)
                            item.appendChild(self.dom.createTextNode(entry[1]))
            elif isinstance(prop, minidom.Attr):
                assert prop.ownerElement is not None
                prop.ownerElement.removeAttributeNode(prop)
            else:
                assert prop.parentNode is not None
                prop.parentNode.removeChild(prop)
        if pending and target is None:
            target = _append(_append(self.subject(), DC, "dc:title"), RDF, "rdf:Alt")
        for tag, value in pending.values():
            assert target is not None
            item = _append(target, RDF, "rdf:li")
            item.setAttributeNS(XML, "xml:lang", tag)
            item.appendChild(self.dom.createTextNode(value))
            if tag.lower() == "x-default" and target.firstChild is not item:
                target.insertBefore(item, target.firstChild)

    @staticmethod
    def _value_node(prop: minidom.Element, container: str, *, create: bool) -> minidom.Element | None:
        groups = _children(prop, RDF, container) if container else []
        if groups:
            items = _children(groups[0], RDF, "li")
            if container == "Alt":
                items = [item for item in items if item.getAttributeNS(XML, "lang") == "x-default"]
            if items:
                return items[0]
            if not create:
                return None
            group = groups[0]
        elif container and not prop.childNodes and create:
            group = _append(prop, RDF, f"rdf:{container}")
        else:
            return prop
        item = _append(group, RDF, "rdf:li")
        if container == "Alt":
            item.setAttributeNS(XML, "xml:lang", "x-default")
            if group.firstChild is not item:
                group.insertBefore(item, group.firstChild)
        return item

    def read(self, key: str) -> str:
        """Read the default translation, first creator, or scalar value."""
        namespace, name, container = FIELDS[key]
        for prop in self._properties(namespace, name.split(":")[1]):
            if isinstance(prop, minidom.Attr):
                return prop.value
            node = self._value_node(prop, container, create=False)
            if node is not None:
                return "".join(child.data for child in node.childNodes if isinstance(child, minidom.Text))
        return ""

    def update(self, key: str, value: str) -> None:
        """Update a common property, preserving translations and additional creators."""
        namespace, name, container = FIELDS[key]
        props = self._properties(namespace, name.split(":")[1])
        if not props and value:
            props.append(_append(self.subject(), namespace, name))
        for prop in props:
            if isinstance(prop, minidom.Attr):
                if value:
                    prop.value = value
                else:
                    assert prop.ownerElement is not None
                    prop.ownerElement.removeAttributeNode(prop)
                continue
            node = self._value_node(prop, container, create=bool(value))
            if node is None:
                continue
            if any(isinstance(child, minidom.Element) for child in node.childNodes):
                raise ValueError(f"Edit the structured {name} property in the XMP tab.")
            if value:
                for child in list(node.childNodes):
                    if isinstance(child, minidom.Text):
                        node.removeChild(child)
                node.appendChild(self.dom.createTextNode(value))
            else:
                parent = node.parentNode
                assert isinstance(parent, minidom.Element)
                parent.removeChild(node)
                if node is not prop and not _children(parent, RDF, "li") and prop.parentNode:
                    prop.parentNode.removeChild(prop)

    def add_profile(self, profile: str) -> None:
        """Write a PDF/A identification after the caller removes previous markers."""
        if profile not in PROFILES:
            raise ValueError(f"Unknown PDF/A profile: {profile}")
        properties = {"part": profile[0]}
        if profile[0] == "4":
            properties["rev"] = "2020"
        if profile[1:]:
            properties["conformance"] = profile[1:].upper()
        for name, value in properties.items():
            prop = _append(self.subject(), PDFA, f"pdfaid:{name}")
            prop.appendChild(self.dom.createTextNode(value))
