from copy import deepcopy
from datetime import date, datetime
from enum import Enum
import json
import sys
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import UUID4, BaseModel, ByteSize, EmailStr, Field, HttpUrl, validator
from ruamel import yaml

from .consts import DANDI_SCHEMA_VERSION
from .model_types import (
    AccessTypeDict,
    DigestTypeDict,
    IdentifierTypeDict,
    LicenseTypeDict,
    ParticipantRelationTypeDict,
    RelationTypeDict,
    RoleTypeDict,
)
from .utils import name2title

if sys.version_info < (3, 8):
    from typing_extensions import Literal
else:
    from typing import Literal

TempOptional = Optional


def create_enum(data):
    """Convert a JSON-LD enumeration to an Enum"""
    items = {}
    klass = None
    for idx, item in enumerate(data["@graph"]):
        if item["@type"] == "rdfs:Class":
            klass = item["@id"].replace("dandi:", "")
            klass_doc = item["rdfs:comment"]
        else:
            key = item["@id"]
            if ":" in item["@id"]:
                key = item["@id"].split(":")[-1]
            if key in items:
                key = item["@id"].replace(":", "_")
            items[key.replace("-", "_")] = item["@id"]
    if klass is None or len(items) == 0:
        raise ValueError(f"Could not generate a klass or items from {data}")
    newklass = Enum(klass, items)
    newklass.__doc__ = klass_doc
    return newklass


def split_name(name):
    space_added = []
    for c in name:
        if c.upper() == c:
            space_added.append(" ")
        space_added.append(c)
    labels = "".join(space_added).split()
    labels[0] = labels[0].capitalize()
    for idx in range(1, len(labels)):
        labels[idx] = labels[idx].lower()
    return " ".join(labels)


def model2graph(model):
    """Convert a model to a JSON-LD graph"""
    klass = {}
    klass["rdfs:comment"] = model.__doc__
    klass["rdfs:label"] = split_name(model.__name__)
    klass["rdf:type"] = "rdfs:Class"
    for key, val in model._ldmeta.items():
        if key == "nskey":
            klass["@id"] = f"{val}:{model.__name__}"
        else:
            klass[key] = val
    graph = [dict(sorted(klass.items()))]
    for key, val in sorted(model.__fields__.items()):
        prefix = val.field_info.extra["nskey"]
        prop = {"@id": f"{prefix}:{key}"}
        prop["schema:domainIncludes"] = klass["@id"]
        if prefix != "schema":
            prop["@type"] = "rdf:Property"
            if val.field_info.title:
                prop["rdfs:label"] = val.field_info.title
            else:
                prop["rdfs:label"] = split_name(key)
            if val.field_info.description:
                prop["rdfs:comment"] = val.field_info.description
            if "rangeIncludes" in val.field_info.extra:
                prop["schema:rangeIncludes"] = val.field_info.extra["rangeIncludes"]
        graph.append(dict(sorted(prop.items())))
    jsonld_doc = {"@context": "../context/base.json", "@graph": graph}
    with open(f"terms/{model.__name__}.yaml", "w") as fp:
        fp.write("# AUTOGENERATED - DO NOT EDIT\n")
        yaml.safe_dump(jsonld_doc, fp, indent=2)
    return jsonld_doc


AccessType = create_enum(AccessTypeDict)
RoleType = create_enum(RoleTypeDict)
RelationType = create_enum(RelationTypeDict)
ParticipantRelationType = create_enum(ParticipantRelationTypeDict)
LicenseType = create_enum(LicenseTypeDict)
IdentifierType = create_enum(IdentifierTypeDict)
DigestType = create_enum(DigestTypeDict)


def diff_models(model1, model2):
    """Perform a field-wise diff"""
    for field in model1.__fields__:
        if getattr(model1, field) != getattr(model2, field):
            print(f"{field} is different")


def to_datacite(dandiset):
    from .metadata import migrate2newschema

    meta = dandiset.metadata
    newmeta = migrate2newschema(meta)

    prefix = "10.80507"
    dandiset_id = dandiset.identifier

    version_id = newmeta.version  # this is None e.g. for 08, what should I use?
    # taken from dandi-api
    doi = f"{prefix}/{dandiset_id}/{version_id}"
    url = f"https://dandiarchive.org/dandiset/{dandiset_id}/{version_id}"

    attributes = {}
    # from the examples I understand that many fields should be provided as a list,
    # even identifier or a title
    attributes["identifiers"] = (
        [
            {
                "identifier": "https://doi.org/10.5438/0012",
                # not sure if I can use it in the schema description the only option is DOI...
                "identifierType": "Dandi",
            }
        ],
    )
    attributes["titles"] = [{"title": newmeta.name}]
    attributes["descriptions"] = [
        {"description": newmeta.description, "descriptionType": "Other"}
    ]
    attributes["publisher"] = "DANDI Archive"
    attributes["publicationYear"] = datetime.now().year
    # not sure about it dandi-api had "resourceTypeGeneral": "NWB"
    attributes["types"] = {"resourceType": "NWB", "resourceTypeGeneral": "Dataset"}
    attributes["url"] = url
    attributes["rightsList"] = [{"rights": newmeta.license}]
    # not sure if these is correct schema or should I provide newmeta.schemaVersion
    # if not here, i'm not sure where newmeta.schemaVersion should go
    attributes["schemaVersion"] = "http://datacite.org/schema/kernel-4"

    contributors = []
    create_dict = {}
    for contr_el in newmeta.contributor:
        if not create_dict and isinstance(contr_el, Person):
            # "name" is not officially in the schema, but its in the example, should I keep it?
            create_dict["name"] = (contr_el["name"],)
            create_dict["creatorName"] = (contr_el["name"],)
            # I'm assuming that we do not have to have Family Name and First name
            create_dict["schemeURI"] = ("orcid.org",)
            create_dict["affiliation"] = contr_el["affiliation"]
            create_dict["nameType"] = "Personal"
        else:
            contr_dict = {
                "name": contr_el["name"],
                "contributorName": contr_el["name"],
                "schemeURI": "orcid.org",
                "affiliation": contr_el["affiliation"],
                # it's not clear to me if schema allows this to be a list
                "contributorType": contr_el["roleName"],
            }
            if isinstance(contr_el, Person):
                contr_dict["nameType"] = "Personal"
            elif isinstance(contr_el, Organization):
                contr_dict["nameType"] = "Organizational"
            contributors.append(contr_dict)

    attributes["contributors"] = contributors
    attributes["creators"] = [create_dict]

    datacite_dict = {"data": {"id": doi, "type": "dois", "attributes": attributes}}
    return datacite_dict


class DandiBaseModel(BaseModel):
    @classmethod
    def unvalidated(__pydantic_cls__: Type[BaseModel], **data: Any) -> BaseModel:
        """Allow model to be returned without validation"""
        for name, field in __pydantic_cls__.__fields__.items():
            try:
                data[name]
            except KeyError:
                # if field.required:
                #    value = None
                if field.default_factory is not None:
                    value = field.default_factory()
                elif field.default is None:
                    # deepcopy is quite slow on None
                    value = None
                else:
                    value = deepcopy(field.default)
                data[name] = value
        self = __pydantic_cls__.__new__(__pydantic_cls__)
        object.__setattr__(self, "__dict__", data)
        object.__setattr__(self, "__fields_set__", set(data.keys()))
        return self

    @classmethod
    def to_dictrepr(__pydantic_cls__: Type[BaseModel]):
        return (
            __pydantic_cls__.unvalidated()
            .__repr__()
            .replace(__pydantic_cls__.__name__, "dict")
        )

    class Config:
        @staticmethod
        def schema_extra(schema: Dict[str, Any], model) -> None:
            schema["title"] = name2title(schema["title"])
            for prop, value in schema.get("properties", {}).items():
                if value.get("title") is None or value["title"] == prop.title():
                    value["title"] = name2title(prop)
                allOf = value.get("allOf")
                anyOf = value.get("anyOf")
                items = value.get("items")
                if allOf is not None:
                    if len(allOf) == 1 and "$ref" in allOf[0]:
                        value["$ref"] = allOf[0]["$ref"]
                        del value["allOf"]
                    elif len(allOf) > 1:
                        value["oneOf"] = value["allOf"]
                        value["type"] = "object"
                        del value["allOf"]
                if anyOf is not None:
                    if len(anyOf) > 1 and any(["$ref" in val for val in anyOf]):
                        value["type"] = "object"
                if items is not None:
                    anyOf = items.get("anyOf")
                    if (
                        anyOf is not None
                        and len(anyOf) > 1
                        and any(["$ref" in val for val in anyOf])
                    ):
                        value["items"]["type"] = "object"
                # In pydantic 1.8+ all Literals are mapped on to enum
                # This presently breaks the schema editor UI. Revert
                # to const when generating the schema.
                if prop == "schemaKey":
                    if len(value["enum"]) == 1:
                        value["const"] = value["enum"][0]
                        del value["enum"]


class PropertyValue(DandiBaseModel):
    maxValue: float = Field(None, nskey="schema")
    minValue: float = Field(None, nskey="schema")
    unitText: str = Field(None, nskey="schema")
    value: Union[Any, List[Any]] = Field(None, nskey="schema")
    valueReference: "PropertyValue" = Field(
        None, nskey="schema"
    )  # Note: recursive (circular or not)
    propertyID: Union[IdentifierType, HttpUrl] = Field(
        None,
        description="A commonly used identifier for"
        "the characteristic represented by the property.",
        nskey="schema",
    )

    _ldmeta = {"nskey": "schema"}


PropertyValue.update_forward_refs()

Identifier = str
ORCID = Identifier
RORID = HttpUrl
DANDI = Identifier
RRID = Identifier


class TypeModel(DandiBaseModel):
    """Base class for enumerated types"""

    identifier: Optional[HttpUrl] = Field(nskey="schema")
    name: Optional[str] = Field(
        description="The name of the item.", max_length=150, nskey="schema"
    )
    schemaKey: Literal["GenericType"] = Field("GenericType", readOnly=True)
    _ldmeta = {"rdfs:subClassOf": ["prov:Entity", "schema:Thing"], "nskey": "dandi"}


class AssayType(TypeModel):
    """OBI based identifier for the assay(s) used"""

    schemaKey: Literal["AssayType"] = Field("AssayType", readOnly=True)


class SampleType(TypeModel):
    """OBI based identifier for the sample type used"""

    schemaKey: Literal["SampleType"] = Field("SampleType", readOnly=True)


class Anatomy(TypeModel):
    """UBERON or other identifier for anatomical part studied"""

    schemaKey: Literal["Anatomy"] = Field("Anatomy", readOnly=True)


class StrainType(TypeModel):
    """Identifier for the strain of the sample"""

    schemaKey: Literal["StrainType"] = Field("StrainType", readOnly=True)


class SexType(TypeModel):
    """Identifier for the sex of the sample"""

    schemaKey: Literal["SexType"] = Field("SexType", readOnly=True)


class SpeciesType(TypeModel):
    """Identifier for species of the sample"""

    schemaKey: Literal["SpeciesType"] = Field("SpeciesType", readOnly=True)


class Disorder(TypeModel):
    """Biolink, SNOMED, or other identifier for disorder studied"""

    dxdate: Optional[List[date]] = Field(
        None,
        title="Dates of diagnosis",
        description="Dates of diagnosis",
        nskey="dandi",
        rangeIncludes="schema:Date",
    )
    schemaKey: Literal["Disorder"] = Field("Disorder", readOnly=True)


class ApproachType(TypeModel):
    """Identifier for approach used"""

    schemaKey: Literal["ApproachType"] = Field("ApproachType", readOnly=True)


class MeasurementTechniqueType(TypeModel):
    """Identifier for measurement technique used"""

    schemaKey: Literal["MeasurementTechniqueType"] = Field(
        "MeasurementTechniqueType", readOnly=True
    )


class StandardsType(TypeModel):
    """Identifier for data standard used"""

    schemaKey: Literal["StandardsType"] = Field("StandardsType", readOnly=True)


class ContactPoint(DandiBaseModel):
    email: Optional[EmailStr] = Field(None, nskey="schema")
    url: Optional[HttpUrl] = Field(None, nskey="schema")

    schemaKey: Literal["ContactPoint"] = Field("ContactPoint", readOnly=True)
    _ldmeta = {"nskey": "schema"}


class Contributor(DandiBaseModel):
    identifier: Optional[Identifier] = Field(
        None,
        title="A Common Identifier",
        description="Use a common identifier such as ORCID for people or ROR for institutions",
        nskey="schema",
    )
    name: Optional[str] = Field(None, nskey="schema")
    email: Optional[EmailStr] = Field(None, nskey="schema")
    url: Optional[HttpUrl] = Field(None, nskey="schema")
    roleName: Optional[List[RoleType]] = Field(
        None, title="Role", description="Role of the contributor", nskey="schema"
    )
    includeInCitation: bool = Field(
        True,
        title="Include Contributor in Citation",
        description="A flag to indicate whether a contributor should be included "
        "when generating a citation for the item",
        nskey="dandi",
    )
    awardNumber: Optional[Identifier] = Field(
        None,
        title="Identifier for an award",
        description="Identifier associated with a sponsored or gift award",
        nskey="dandi",
    )


class Organization(Contributor):
    identifier: Optional[RORID] = Field(
        None,
        title="A ror.org identifier",
        description="Use an ror.org identifier for institutions",
        pattern=r"^https://ror.org/[a-z0-9]+$",
        nskey="schema",
    )

    includeInCitation: bool = Field(
        False,
        title="Include Contributor in Citation",
        description="A flag to indicate whether a contributor should be included "
        "when generating a citation for the item",
        nskey="dandi",
    )
    contactPoint: Optional[List[ContactPoint]] = Field(
        None, description="Contact for the organization", nskey="schema"
    )
    schemaKey: Literal["Organization"] = Field("Organization", readOnly=True)
    _ldmeta = {
        "rdfs:subClassOf": ["schema:Organization", "prov:Organization"],
        "nskey": "dandi",
    }


class Person(Contributor):
    identifier: Optional[ORCID] = Field(
        None,
        title="An ORCID Identifier",
        description="An ORCID (orcid.org) identifier for an individual",
        pattern=r"^\d{4}-\d{4}-\d{4}-(\d{3}X|\d{4})$",
        nskey="schema",
    )
    name: str = Field(
        description="Use the format: lastname, firstname ...", nskey="schema"
    )
    affiliation: List[Organization] = Field(
        None,
        description="An organization that this person is affiliated with.",
        nskey="schema",
    )
    schemaKey: Literal["Person"] = Field("Person", readOnly=True)

    _ldmeta = {"rdfs:subClassOf": ["schema:Person", "prov:Person"], "nskey": "dandi"}


class Software(DandiBaseModel):
    identifier: Optional[RRID] = Field(
        None,
        pattern=r"^RRID\:.*",
        title="Research Resource Identifier",
        description="RRID of the software from scicrunch.org.",
        nskey="schema",
    )
    name: str = Field(nskey="schema")
    version: str = Field(nskey="schema")
    url: Optional[HttpUrl] = Field(None, nskey="schema")
    schemaKey: Literal["Software"] = Field("Software", readOnly=True)

    _ldmeta = {
        "rdfs:subClassOf": ["schema:SoftwareApplication", "prov:Software"],
        "nskey": "dandi",
    }


class EthicsApproval(DandiBaseModel):
    """Information about ethics committee approval for project"""

    identifier: Identifier = Field(
        nskey="schema",
        title="Approved protocol identifier",
        description="Approved Protocol identifier, often a number or alpha-numeric string.",
    )
    contactPoint: ContactPoint = Field(
        description="Information about the ethics approval committee.", nskey="schema"
    )

    _ldmeta = {"rdfs:subClassOf": ["schema:Thing", "prov:Entity"], "nskey": "dandi"}


class Resource(DandiBaseModel):
    identifier: Optional[Identifier] = Field(None, nskey="schema")
    name: Optional[str] = Field(None, title="A title of the resource", nskey="schema")
    url: HttpUrl = Field(None, title="URL of the resource", nskey="schema")
    repository: Optional[str] = Field(
        None,
        title="Name of the repository",
        description="Name of the repository in which the resource is housed",
        nskey="dandi",
    )
    relation: RelationType = Field(
        title="Choose a relation satisfying: Dandiset <relation> Resource",
        description="Indicates how the resource is related to the dataset. "
        "This relation should satisfy: dandiset <relation> resource",
        nskey="dandi",
    )

    _ldmeta = {
        "rdfs:subClassOf": ["schema:CreativeWork", "prov:Entity"],
        "rdfs:comment": "A resource related to the project (e.g., another "
        "dataset, publication, Webpage)",
        "nskey": "dandi",
    }


class AccessRequirements(DandiBaseModel):
    """Information about access options for the dataset"""

    status: AccessType = Field(
        title="Access status",
        description="The access status of the item",
        nskey="dandi",
    )
    contactPoint: Optional[ContactPoint] = Field(
        None,
        description="Who or where to look for information about access",
        nskey="schema",
    )
    description: Optional[str] = Field(
        None,
        description="Information about access requirements when embargoed or restricted",
        nskey="schema",
    )
    embargoedUntil: Optional[date] = Field(
        None,
        title="Embargo end date",
        description="Date on which embargo ends",
        readOnly=True,
        nskey="dandi",
        rangeIncludes="schema:Date",
    )

    _ldmeta = {"rdfs:subClassOf": ["schema:Thing", "prov:Entity"], "nskey": "dandi"}


class AssetsSummary(DandiBaseModel):
    """Summary over assets contained in a dandiset (published or not)"""

    # stats which are not stats
    numberOfBytes: int = Field(readOnly=True, sameas="schema:contentSize")
    numberOfFiles: int = Field(readOnly=True)  # universe
    numberOfSubjects: int = Field(readOnly=True)  # NWB + BIDS
    numberOfSamples: Optional[int] = Field(None, readOnly=True)  # more of NWB
    numberOfCells: Optional[int] = Field(None, readOnly=True)

    dataStandard: List[StandardsType] = Field(
        readOnly=True
    )  # TODO: types of things NWB, BIDS
    # Web UI: icons per each modality?
    approach: List[ApproachType] = Field(
        readOnly=True
    )  # TODO: types of things, BIDS etc...
    # Web UI: could be an icon with number, which if hovered on  show a list?
    measurementTechnique: List[MeasurementTechniqueType] = Field(readOnly=True)
    variableMeasured: Optional[List[str]] = Field(None, readOnly=True)

    species: List[SpeciesType] = Field(readOnly=True)

    _ldmeta = {
        "rdfs:subClassOf": ["schema:CreativeWork", "prov:Entity"],
        "nskey": "dandi",
    }


class Digest(DandiBaseModel):
    """Information about the crytographic checksum of the item."""

    value: str = Field(nskey="schema")
    cryptoType: DigestType = Field(
        title="Cryptographic method used",
        description="Which cryptographic checksum is used",
        nskey="dandi",
    )

    _ldmeta = {
        "rdfs:subClassOf": ["schema:Thing", "prov:Entity"],
        "rdfs:label": "Cryptographic checksum information",
        "nskey": "dandi",
    }


class BioSample(DandiBaseModel):
    """Description about the sample that was studied"""

    identifier: Identifier = Field(nskey="schema")
    sampleType: Optional[SampleType] = Field(
        None, description="OBI based identifier for the sample used", nskey="dandi"
    )
    assayType: Optional[List[AssayType]] = Field(
        None, description="OBI based identifier for the assay(s) used", nskey="dandi"
    )
    anatomy: Optional[List[Anatomy]] = Field(
        None,
        description="UBERON based identifier for what organ the sample belongs "
        "to. Use the most specific descriptor.",
        nskey="dandi",
    )

    wasDerivedFrom: Optional[List["BioSample"]] = Field(None, nskey="prov")
    sameAs: Optional[List[Identifier]] = Field(None, nskey="schema")
    hasMember: Optional[List[Identifier]] = Field(None, nskey="prov")

    schemaKey: Literal["BioSample"] = Field("BioSample", readOnly=True)

    _ldmeta = {
        "rdfs:subClassOf": ["schema:Thing", "prov:Entity"],
        "rdfs:label": "Information about the biosample.",
        "nskey": "dandi",
    }


BioSample.update_forward_refs()


class RelatedParticipant(DandiBaseModel):
    identifier: Optional[Identifier] = Field(None, nskey="schema")
    name: Optional[str] = Field(None, title="A title of the resource", nskey="schema")
    url: Optional[HttpUrl] = Field(None, title="URL of the resource", nskey="schema")
    relation: ParticipantRelationType = Field(
        title="Choose a relation satisfying: Participant <relation> relatedParticipant",
        description="Indicates how the current participant is related to the other participant "
        "This relation should satisfy: Participant <relation> relatedParticipant",
        nskey="dandi",
    )

    _ldmeta = {
        "rdfs:subClassOf": ["schema:CreativeWork", "prov:Entity"],
        "rdfs:comment": "Another participant related to the participant (e.g., another "
        "parent, sibling, child)",
        "nskey": "dandi",
    }


class Participant(DandiBaseModel):
    """Description about the sample that was studied"""

    identifier: Identifier = Field(nskey="schema")
    source_id: Optional[Identifier] = Field(None, nskey="dandi")

    strain: Optional[StrainType] = Field(
        None, description="Identifier for the strain of the sample", nskey="dandi"
    )
    cellLine: Optional[Identifier] = Field(
        None, description="Cell line associated with the sample", nskey="dandi"
    )
    vendor: Optional[Organization] = Field(None, nskey="dandi")
    age: Optional[PropertyValue] = Field(
        None,
        description="A representation of age using ISO 8601 duration. This "
        "should include a valueReference if anything other than "
        "date of birth is used.",
        nskey="dandi",
        rangeIncludes="schema:Duration",
    )
    sex: Optional[SexType] = Field(
        None,
        description="OBI based identifier for sex of the sample if available",
        nskey="dandi",
    )
    genotype: Optional[Identifier] = Field(
        None, description="Genotype descriptor of biosample if available", nskey="dandi"
    )
    species: Optional[SpeciesType] = Field(
        None,
        description="An identifier indicating the taxonomic classification of the biosample",
        nskey="dandi",
    )
    disorder: Optional[List[Disorder]] = Field(
        None,
        description="Any current diagnosed disease or disorder associated with the sample",
        nskey="dandi",
    )
    relatedParticipant: Optional[List[RelatedParticipant]] = Field(None, nskey="dandi")

    schemaKey: Literal["Participant"] = Field("Participant", readOnly=True)

    _ldmeta = {
        "rdfs:subClassOf": ["schema:Thing", "prov:Entity"],
        "rdfs:label": "Information about the participant.",
        "nskey": "dandi",
    }


class Activity(DandiBaseModel):
    """Information about the Project activity"""

    identifier: Optional[Identifier] = Field(None, nskey="schema")
    name: str = Field(
        title="Title",
        description="The name of the item.",
        max_length=150,
        nskey="schema",
    )
    description: Optional[str] = Field(
        None, description="A description of the item.", nskey="schema"
    )
    startDate: Optional[date] = Field(None, nskey="schema")
    endDate: Optional[date] = Field(None, nskey="schema")

    # isPartOf: Optional["Activity"] = Field(None, nskey="schema")
    # hasPart: Optional["Activity"] = Field(None, nskey="schema")
    wasAssociatedWith: Optional[List[Union[Person, Organization, Software]]] = Field(
        None, nskey="prov"
    )

    schemaKey: Literal["Activity"] = Field("Activity", readOnly=True)

    _ldmeta = {"rdfs:subClassOf": ["prov:Activity", "schema:Thing"], "nskey": "dandi"}


# Activity.update_forward_refs()


class Project(Activity):
    name: str = Field(
        title="Title",
        description="The name of the project that generated this Dandiset or asset.",
        max_length=150,
        nskey="schema",
    )
    description: Optional[str] = Field(
        None, description="A brief description of the project.", nskey="schema"
    )
    schemaKey: Literal["Project"] = Field("Project", readOnly=True)


class Session(Activity):
    name: str = Field(
        title="Title",
        description="The name of the logical session associated with the asset.",
        max_length=150,
        nskey="schema",
    )
    description: Optional[str] = Field(
        None, description="A brief description of the session.", nskey="schema"
    )
    schemaKey: Literal["Session"] = Field("Session", readOnly=True)


class Identifiable(DandiBaseModel):
    identifier: Identifier = Field(readOnly=True, nskey="schema")


class CommonModel(DandiBaseModel):
    schemaVersion: str = Field(
        default=DANDI_SCHEMA_VERSION, readOnly=True, nskey="schema"
    )
    name: Optional[str] = Field(
        None,
        title="Title",
        description="The name of the item.",
        max_length=150,
        nskey="schema",
    )
    description: Optional[str] = Field(
        None, description="A description of the item.", nskey="schema"
    )
    contributor: Optional[List[Union[Person, Organization]]] = Field(
        None,
        title="Contributors",
        description="Contributors to this item.",
        nskey="schema",
    )
    about: Optional[List[Union[Disorder, Anatomy, TypeModel]]] = Field(
        None,
        title="Subject Matter",
        description="The subject matter of the content, such as disorders, brain anatomy.",
        nskey="schema",
    )
    studyTarget: Optional[List[str]] = Field(
        None, description="What the study is related to", nskey="dandi"
    )
    license: List[LicenseType] = Field(description="License of item.", nskey="schema")
    protocol: Optional[List[HttpUrl]] = Field(
        None, description="A list of protocol.io URLs", nskey="dandi"
    )
    ethicsApproval: Optional[List[EthicsApproval]] = Field(None, nskey="dandi")
    keywords: Optional[List[str]] = Field(
        None,
        description="Keywords or tags used to describe "
        "this content. Multiple entries in a "
        "keywords list are typically delimited "
        "by commas.",
        nskey="schema",
    )
    acknowledgement: Optional[str] = Field(None, nskey="dandi")

    # Linking to this dandiset or the larger thing
    access: List[AccessRequirements] = Field(
        title="Access Type",
        default_factory=lambda: [AccessRequirements(status=AccessType.Open)],
        nskey="dandi",
    )
    url: Optional[HttpUrl] = Field(
        None, readOnly=True, description="permalink to the item", nskey="schema"
    )
    repository: HttpUrl = Field(
        "https://dandiarchive.org/",
        readOnly=True,
        description="location of the item",
        nskey="dandi",
    )
    relatedResource: Optional[List[Resource]] = Field(None, nskey="dandi")

    wasGeneratedBy: Optional[List[Activity]] = Field(None, nskey="prov")

    def json_dict(self):
        """
        Recursively convert the instance to a `dict` of JSONable values,
        including converting enum values to strings.  `None` fields
        are omitted.
        """
        return json.loads(self.json(exclude_none=True))


class DandisetMeta(CommonModel, Identifiable):
    """A body of structured information describing a DANDI dataset."""

    @validator("contributor")
    def check_data(cls, values):
        contacts = []
        for val in values:
            if val.roleName and RoleType.ContactPerson in val.roleName:
                contacts.append(val)
        if len(contacts) == 0:
            raise ValueError("At least one contributor must have role ContactPerson")
        return values

    identifier: DANDI = Field(
        readOnly=True,
        title="Dandiset identifier",
        description="A Dandiset identifier that can be resolved by identifiers.org",
        pattern=r"^DANDI\:\d{6}$",
        nskey="schema",
    )
    name: str = Field(
        title="Dandiset Title",
        description="A title associated with the Dandiset.",
        max_length=150,
        nskey="schema",
    )

    description: str = Field(
        description="A description of the Dandiset", max_length=3000, nskey="schema"
    )
    contributor: List[Union[Person, Organization]] = Field(
        title="Dandiset contributors",
        description="People or Organizations that have contributed to this Dandiset.",
        nskey="schema",
        min_items=1,
    )

    citation: TempOptional[str] = Field(readOnly=True, nskey="schema")

    # From assets
    assetsSummary: TempOptional[AssetsSummary] = Field(readOnly=True, nskey="dandi")

    # From server (requested by users even for drafts)
    manifestLocation: TempOptional[List[HttpUrl]] = Field(readOnly=True, nskey="dandi")

    # On publish
    version: TempOptional[str] = Field(readOnly=True, nskey="schema")
    doi: Optional[str] = Field(
        None,
        title="DOI",
        readOnly=True,
        pattern=r"^10\.[A-Za-z0-9.\/-]+",
        nskey="dandi",
    )

    wasGeneratedBy: Optional[List[Project]] = Field(
        None,
        title="Name of the project",
        description="Describe the project(s) that generated this Dandiset",
        nskey="prov",
    )

    _ldmeta = {
        "rdfs:subClassOf": ["schema:Dataset", "prov:Entity"],
        "rdfs:label": "Information about the dataset",
        "nskey": "dandi",
    }


class PublishedDandisetMeta(DandisetMeta):
    publishedBy: HttpUrl = Field(
        description="The URL should contain the provenance of the publishing process.",
        readOnly=True,
        nskey="dandi",
    )  # TODO: formalize "publish" activity to at least the Actor
    datePublished: date = Field(readOnly=True, nskey="schema")


class BareAssetMeta(CommonModel):
    """Metadata used to describe an asset anywhere (local or server).

    Derived from C2M2 (Level 0 and 1) and schema.org
    """

    # Overrides CommonModel.license
    # TODO: https://github.com/NeurodataWithoutBorders/nwb-schema/issues/320
    license: Optional[List[LicenseType]] = Field(
        None, description="License of item", nskey="schema"
    )

    contentSize: ByteSize = Field(nskey="schema")
    encodingFormat: Union[HttpUrl, str] = Field(
        title="File Encoding Format", nskey="schema"
    )
    digest: List[Digest] = Field(nskey="dandi", default_factory=list)
    dateModified: Optional[datetime] = Field(
        nskey="schema", title="Asset (file or metadata) modification date and time"
    )
    blobDateModified: Optional[datetime] = Field(
        nskey="dandi", title="Asset file modification date and time"
    )

    path: str = Field(None, nskey="dandi")

    # this is from C2M2 level 1 - using EDAM vocabularies - in our case we would
    # need to come up with things for neurophys
    # TODO: waiting on input <https://github.com/dandi/dandi-cli/pull/226>
    dataType: Optional[HttpUrl] = Field(None, nskey="dandi")

    sameAs: Optional[List[HttpUrl]] = Field(None, nskey="schema")

    # TODO
    approach: Optional[List[ApproachType]] = Field(None, readOnly=True, nskey="dandi")
    measurementTechnique: Optional[List[MeasurementTechniqueType]] = Field(
        None, readOnly=True, nskey="schema"
    )
    variableMeasured: Optional[List[PropertyValue]] = Field(
        None, readOnly=True, nskey="schema"
    )

    wasDerivedFrom: Optional[List[BioSample]] = Field(None, nskey="prov")
    wasAttributedTo: List[Participant] = Field(
        None, description="Participant(s) to which this file belongs to", nskey="prov"
    )
    wasGeneratedBy: Optional[List[Union[Session, Project, Activity]]] = Field(
        None,
        title="Name of the session, project or activity.",
        description="Describe the session, project or activity that generated this asset",
        nskey="prov",
    )

    _ldmeta = {
        "rdfs:subClassOf": ["schema:CreativeWork", "prov:Entity"],
        "rdfs:label": "Information about the asset",
        "nskey": "dandi",
    }


class AssetMeta(BareAssetMeta, Identifiable):
    """Metadata used to describe an asset on the server."""

    identifier: UUID4 = Field(readOnly=True, nskey="schema")

    # on publish or set by server
    contentUrl: Optional[List[HttpUrl]] = Field(None, readOnly=True, nskey="schema")


class PublishedAssetMeta(AssetMeta):
    publishedBy: HttpUrl = Field(
        description="The URL should contain the provenance of the publishing process.",
        readOnly=True,
        nskey="dandi",
    )  # TODO: formalize "publish" activity to at least the Actor
    datePublished: date = Field(readOnly=True, nskey="schema")


def get_schema_version():
    return DANDI_SCHEMA_VERSION
