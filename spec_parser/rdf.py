# saving the model as RDF

# SPDX-License-Identifier: Apache-2.0

import json
import logging
from pathlib import Path

from rdflib import (
    BNode,
    Graph,
    Literal,
    Namespace,
    URIRef,
)
from rdflib.namespace import (
    OWL, RDF, RDFS, SH, XSD, DefinedNamespace, Namespace,
)
from rdflib.tools.rdf2dot import (
    rdf2dot
)


URI_BASE = 'https://rdf.spdx.org/v3/'

# Custom SPDX schema properties
class SPDXS(DefinedNamespace):
    referenceable: URIRef
    idPropertyName: URIRef
    _NS = Namespace("https://rdf.spdx.org/ns/schema#")


def gen_rdf(model, dir, cfg):
    p = Path(dir)
    p.mkdir(exist_ok=True)

    ret = gen_rdf_ontology(model)
    for ext in ["xml", "ttl", "pretty-xml", "json-ld"]:
        f = p / ("ontology.rdf." + ext)
        ret.serialize(f, format=ext, encoding="utf-8")
    fn = p / "ontology.rdf.dot"
    with open(fn, "w") as f:
        rdf2dot(ret, f)
    ctx = jsonld_context(ret)
    fn = p / "context.jsonld"
    with open(fn, "w") as f:
        json.dump(ctx, f, sort_keys=True, indent=2)


def xsd_range(rng, propname):
    if rng.startswith('xsd:'):
        return URIRef("http://www.w3.org/2001/XMLSchema#"+rng[4:])

    logging.warn(f'Uknown namespace in range <{rng}> of property {propname}')
    return None

def get_parent(c, model):
    parent = c.metadata.get("SubclassOf")
    if not parent:
        return None
    pns = "" if parent.startswith("/") else f"/{c.ns.name}/"
    return model.classes[pns+parent]

def gen_rdf_ontology(model):
    g = Graph()
    g.bind("spdx", Namespace(URI_BASE))
    g.bind("xsd", XSD)
    g.bind("spdxs", SPDXS)

    node = URIRef(URI_BASE)
    g.add((node, RDF.type, OWL.Ontology))
    g.add((node, OWL.versionIRI, node))

    for fqname, c in model.classes.items():
        node = URIRef(c.iri)
        g.add((node, RDF.type, RDFS.Class))
        g.add((node, RDF.type, OWL.Class))
        if c.summary:
            g.add((node, RDFS.comment, Literal(c.summary, lang='en')))
        parent = get_parent(c, model)
        if parent:
            g.add((node, RDFS.subClassOf, URIRef(parent.iri)))

        id_property = None
        referenceable = None
        parent = c
        while parent:
            if referenceable is None and "Referenceable" in parent.metadata:
                referenceable = parent.metadata["Referenceable"]

            if id_property is None and parent.properties:
                for p in parent.properties:
                    fqprop = parent.properties[p]["fqname"]
                    prop = model.properties[fqprop]
                    if prop.metadata["Nature"] == "IdProperty":
                        id_property = fqprop.rsplit("/")[-1]
                        if prop.ns.name != "Core":
                            id_property = prop.ns.name.lower() + "_" + id_property

            parent = get_parent(parent, model)

        if referenceable is None:
            referenceable = "optional";
        g.add((node, SPDXS.referenceable, Literal(referenceable)))
        if id_property is not None:
            g.add((node, SPDXS.idPropertyName, Literal(id_property)))

        if c.properties:
            g.add((node, RDF.type, SH.NodeShape))
            for p in c.properties:
                fqprop = c.properties[p]["fqname"]
                prop = model.properties[fqprop]
                if prop.metadata["Nature"] == "IdProperty":
                    continue

                bnode = BNode()
                g.add((node, SH.property, bnode))
                g.add((bnode, SH.path, URIRef(prop.iri)))
                prop_rng = prop.metadata["Range"]
                if not ":" in prop_rng:
                    typename = "" if prop_rng.startswith("/") else f"/{prop.ns.name}/"
                    typename += prop_rng
                else:
                    typename = prop_rng

                if typename in model.classes:
                    dt = model.classes[typename]
                    g.add((bnode, SH["class"], URIRef(dt.iri)))
                elif typename in model.vocabularies:
                    dt = model.vocabularies[typename]
                    g.add((bnode, SH["class"], URIRef(dt.iri)))
                elif typename in model.datatypes:
                    dt = model.datatypes[typename]
                    if "pattern" in dt.format:
                        g.add((bnode, SH.pattern, Literal(dt.format["pattern"])))

                    t = xsd_range(dt.metadata["SubclassOf"], prop.iri)
                    if t:
                        g.add((bnode, SH.datatype, t))
                else:
                    t = xsd_range(typename, prop.iri)
                    if t:
                        g.add((bnode, SH.datatype, t))


                mincount = c.properties[p]["minCount"]
                if int(mincount) != 0:
                    g.add((bnode, SH.minCount, Literal(int(mincount))))
                maxcount = c.properties[p]["maxCount"]
                if maxcount != '*':
                    g.add((bnode, SH.maxCount, Literal(int(maxcount))))


    for fqname, p in model.properties.items():
        if p.metadata["Nature"] == "IdProperty":
            continue
        node = URIRef(p.iri)
        g.add((node, RDF.type, RDF.Property))
        if p.summary:
            g.add((node, RDFS.comment, Literal(p.summary, lang='en')))
        if p.metadata["Nature"] == "ObjectProperty":
            g.add((node, RDF.type, OWL.ObjectProperty))
#             g.add((node, RDFS.domain, xxx))
        elif p.metadata["Nature"] == "DataProperty":
            g.add((node, RDF.type, OWL.DatatypeProperty))
        rng = p.metadata["Range"]
        if ':' in rng:
            t = xsd_range(rng, p.name)
            if t:
                g.add((node, RDFS.range, t))
        else:
            typename = "" if rng.startswith("/") else f"/{p.ns.name}/"
            typename += rng
            if typename in model.datatypes:
                t = xsd_range(model.datatypes[typename].metadata["SubclassOf"], p.name)
                if t:
                    g.add((node, RDFS.range, t))
            else:
                dt = model.types[typename]
                g.add((node, RDFS.range, URIRef(dt.iri)))

    for fqname, v in model.vocabularies.items():
        node = URIRef(v.iri)
        g.add((node, RDF.type, RDFS.Class))
        g.add((node, RDF.type, OWL.Class))
        if v.summary:
            g.add((node, RDFS.comment, Literal(v.summary, lang='en')))
        for e, d in v.entries.items():
            enode = URIRef(v.iri + '/' + e)
            g.add((enode, RDF.type, OWL.NamedIndividual))
            g.add((enode, RDF.type, node))
            g.add((enode, RDFS.label, Literal(e)))
            g.add((enode, RDFS.comment, Literal(d, lang='en')))

    for fqname, i in model.individuals.items():
        node = URIRef(i.iri)
        g.add((node, RDF.type, OWL.NamedIndividual))
        if i.summary:
            g.add((node, RDFS.comment, Literal(i.summary, lang='en')))
        typ = i.metadata["type"]
        typename = "" if typ.startswith("/") else f"/{i.ns.name}/"
        typename += typ
        dt = model.types[typename]
        g.add((node, RDFS.range, URIRef(dt.iri)))
        custom_iri = i.metadata.get("IRI")
        if custom_iri:
            g.add((node, OWL.sameAs, URIRef(custom_iri)))

    return g


def jsonld_context(g):
    terms = dict()
    terms["spdx"] = URI_BASE
    terms["type"] = "@type"

    for idname in set(g.objects(predicate=SPDXS.idPropertyName)):
        terms[idname] = "@id"

    def get_subject_term(subject):
        if (subject, RDF.type, OWL.ObjectProperty) in g:
            for _, _, o in g.triples((subject, RDFS.range, None)):
                if o in has_named_individuals:
                    return {
                        "@id": subject,
                        "@type": "@vocab",
                        "@context": {
                            "@vocab": o + "/",
                        },
                    }
                elif (o, RDF.type, RDFS.Class) in g:
                    return {
                        "@id": subject,
                        "@type": "@id",
                    }
        return subject

    has_named_individuals = set()
    # Collect all named individuals
    for s in g.subjects(RDF.type, OWL.NamedIndividual):
        for s, p, o in g.triples((s, RDF.type, None)):
            has_named_individuals.add(o)

    for subject in sorted(g.subjects(unique=True)):
        # Skip named individuals
        if (subject, RDF.type, OWL.NamedIndividual) in g:
            continue

        try:
            base, ns, name = str(subject).rsplit("/", 2)
        except ValueError:
            continue

        if base != URI_BASE.rstrip("/"):
            continue

        if ns == "Core":
            key = name
        else:
            key = ns.lower() + "_" + name

        if key in terms:
            current = terms[key]["@id"] if isinstance(terms[key], dict) else terms[key]
            logging.error(
                f"ERROR: Duplicate context key '{key}' for '{subject}'. Already mapped to '{current}'"
            )
            continue

        terms[key] = get_subject_term(subject)

    return {"@context": terms}
