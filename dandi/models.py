from enum import Enum
from pydantic import BaseModel, Field, AnyUrl, EmailStr, validator
from typing import List, Union, Optional, Any, Type
from datetime import date
from ruamel import yaml
from copy import deepcopy

from .model_types import (
    AccessTypeDict,
    RoleTypeDict,
    RelationTypeDict,
    LicenseTypeDict,
    IdentifierTypeDict,
    DigestTypeDict,
)


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
            items[f"{key}"] = item["@id"]
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
Relation = create_enum(RelationTypeDict)
License = create_enum(LicenseTypeDict)
IdentifierType = create_enum(IdentifierTypeDict)
DigestType = create_enum(DigestTypeDict)


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


class PropertyValue(DandiBaseModel):
    maxValue: float = Field(None, nskey="schema")
    minValue: float = Field(None, nskey="schema")
    unitCode: Union[str, AnyUrl] = Field(None, nskey="schema")
    unitText: str = Field(None, nskey="schema")
    value: Union[str, bool, int, float, List[Union[str, bool, int, float]]] = Field(
        None, nskey="schema"
    )
    valueReference: "PropertyValue" = Field(
        None, nskey="schema"
    )  # Note: recursive (circular or not)
    propertyID: Union[IdentifierType, AnyUrl, str] = Field(None, nskey="schema")

    _ldmeta = {"nskey": "schema"}


PropertyValue.update_forward_refs()
Identifier = Union[AnyUrl, PropertyValue, str]


class TypeModel(DandiBaseModel):
    """Base class for enumerated types"""

    identifier: Optional[Identifier] = Field(nskey="schema")
    name: Optional[str] = Field(
        title="Title",
        description="The name of the item.",
        max_length=150,
        nskey="schema",
    )

    _ldmeta = {"rdfs:subClassOf": ["prov:Entity", "schema:Thing"], "nskey": "dandi"}


class AssayType(TypeModel):
    """OBI based identifier for the assay(s) used"""


class Anatomy(TypeModel):
    """UBERON or other identifier for anatomical part studied"""


class StrainType(TypeModel):
    """Identifier for the strain of the sample"""


class SexType(TypeModel):
    """Identifier for the sex of the sample"""


class SpeciesType(TypeModel):
    """Identifier for species of the sample"""


class Disorder(TypeModel):
    """Biolink, SNOMED, or other identifier for disorder studied"""

    dxdate: Optional[List[date]] = Field(
        None,
        title="Dates of diagnosis",
        description="Dates of diagnosis",
        readOnly=True,
        nskey="dandi",
        rangeIncludes="schema:Date",
    )


class ModalityType(TypeModel):
    """Identifier for modality used"""


class MeasurementTechniqueType(TypeModel):
    """Identifier for measurement technique used"""


class StandardsType(TypeModel):
    """Identifier for data standard used"""


class ContactPoint(DandiBaseModel):
    email: Optional[EmailStr] = Field(None, nskey="schema")
    url: Optional[AnyUrl] = Field(None, nskey="schema")

    _ldmeta = {"nskey": "schema"}


class Contributor(DandiBaseModel):
    identifier: Identifier = Field(None, nskey="schema")
    name: str = Field(None, nskey="schema")
    email: EmailStr = Field(None, nskey="schema")
    url: AnyUrl = Field(None, nskey="schema")
    roleName: List[RoleType] = Field(nskey="schema")
    includeInCitation: bool = Field(
        True,
        title="Include contributor in citation",
        description="A flag to indicate whether a contributor should be included "
        "when generating a citation for the item",
        nskey="dandi",
    )
    awardNumber: Identifier = Field(
        None,
        title="Identifier for an award",
        description="Identifier associated with a sponsored or gidt award",
        nskey="dandi",
    )


class Organization(Contributor):
    contactPoint: List[ContactPoint] = Field(
        description="Contact for the organization", nskey="schema"
    )
    _ldmeta = {
        "rdfs:subClassOf": ["schema:Organization", "prov:Organization"],
        "nskey": "dandi",
    }


class Person(Contributor):
    name: str = Field(
        description="Use the format: lastname, firstname ...",
        title="Name",
        nskey="schema",
    )
    affiliation: List[Organization] = Field(
        None,
        description="An organization that this person is affiliated with.",
        nskey="schema",
    )
    _ldmeta = {"rdfs:subClassOf": ["schema:Person", "prov:Person"], "nskey": "dandi"}


class Software(DandiBaseModel):
    identifier: Identifier = Field(nskey="schema")
    name: str = Field(nskey="schema")
    version: str = Field(nskey="schema")


class EthicsApproval(DandiBaseModel):
    """Information about ethics committee approval for project"""

    identifier: Identifier = Field(nskey="schema")
    contactPoint: ContactPoint = Field(
        description="Information about the ethics approval committee.", nskey="schema"
    )

    _ldmeta = {"rdfs:subClassOf": ["schema:Thing", "prov:Entity"], "nskey": "dandi"}


class Resource(DandiBaseModel):
    identifier: Identifier = Field(None, nskey="schema")
    name: str = Field(None, nskey="schema")
    url: str = Field(None, nskey="schema")
    repository: Union[str, AnyUrl] = Field(
        None,
        description="An identifier of a repository in which the resource is housed",
        nskey="dandi",
    )
    relation: Relation = Field(
        description="Indicates how the resource is related to the dataset",
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
    email: Optional[EmailStr] = Field(None, nskey="schema")
    contactPoint: Optional[ContactPoint] = Field(None, nskey="schema")
    description: Optional[str] = Field(
        None,
        title="Description",
        description="A description of the item.",
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
    modality: List[ModalityType] = Field(
        readOnly=True
    )  # TODO: types of things, BIDS etc...
    # Web UI: could be an icon with number, which if hovered on  show a list?
    measurementTechnique: List[MeasurementTechniqueType] = Field(readOnly=True)
    variableMeasured: Optional[List[PropertyValue]] = Field(None, readOnly=True)

    species: List[SpeciesType] = Field(readOnly=True)

    _ldmeta = {
        "rdfs:subClassOf": ["schema:CreativeWork", "prov:Entity"],
        "nskey": "dandi",
    }


class Digest(DandiBaseModel):
    """Information about the crytographic checksum of the item."""

    value: str = Field(nskey="schema")
    cryptoType: DigestType = Field(
        description="Which cryptographic checksum is used",
        title="Cryptographic method used",
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
    assayType: Optional[List[AssayType]] = Field(
        None, description="OBI based identifier for the assay(s) used", nskey="dandi"
    )
    anatomy: Optional[List[Anatomy]] = Field(
        None,
        description="UBERON based identifier for the location of the sample",
        nskey="dandi",
    )
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

    _ldmeta = {
        "rdfs:subClassOf": ["schema:Thing", "prov:Entity"],
        "rdfs:label": "Information about the biosample.",
        "nskey": "dandi",
    }


class Activity(DandiBaseModel):
    """Information about the Project activity"""

    identifier: Identifier = Field(nskey="schema")
    name: str = Field(
        title="Title",
        description="The name of the item.",
        max_length=150,
        nskey="schema",
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="A description of the item.",
        nskey="schema",
    )
    startDate: Optional[date] = Field(None, nskey="schema")
    endDate: Optional[date] = Field(None, nskey="schema")

    isPartOf: Optional["Activity"] = Field(None, nskey="schema")
    hasPart: Optional["Activity"] = Field(None, nskey="schema")
    wasAssociatedWith: Optional[Union[Person, Organization, Software]] = Field(
        None, nskey="prov"
    )

    _ldmeta = {"rdfs:subClassOf": ["prov:Activity", "schema:Thing"], "nskey": "dandi"}


Activity.update_forward_refs()


class Project(Activity):
    pass


class CommonModel(DandiBaseModel):
    schemaVersion: str = Field(default="1.0.0-rc1", readOnly=True, nskey="schema")
    identifier: Identifier = Field(readOnly=True, nskey="schema")
    name: Optional[str] = Field(
        None,
        title="Title",
        description="The name of the item.",
        max_length=150,
        nskey="schema",
    )
    description: Optional[str] = Field(
        None,
        title="Description",
        description="A description of the item.",
        nskey="schema",
    )
    contributor: Optional[List[Union[Person, Organization]]] = Field(
        None,
        title="Contributors",
        description="Contributors to this item.",
        nskey="schema",
    )
    about: Optional[List[Union[Disorder, Anatomy, Identifier]]] = Field(
        None,
        title="Subject matter",
        description="The subject matter of the content, such as disorders, brain anatomy.",
        nskey="schema",
    )
    studyTarget: Optional[List[Union[str, AnyUrl]]] = Field(
        None, title="What the study is related to", nskey="dandi"
    )
    protocol: Optional[List[str]] = Field(None, nskey="dandi")
    ethicsApproval: Optional[List[EthicsApproval]] = Field(None, nskey="dandi")
    license: List[License] = Field(nskey="schema")
    keywords: Optional[List[str]] = Field(
        None,
        title="Keywords",
        description="Keywords or tags used to describe "
        "this content. Multiple entries in a "
        "keywords list are typically delimited "
        "by commas.",
        nskey="schema",
    )
    acknowledgement: Optional[str] = Field(None, title="Acknowledgement", nskey="dandi")

    # Linking to this dandiset or the larger thing
    access: List[AccessRequirements] = Field(
        default_factory=lambda: [AccessRequirements(status=AccessType.Open)],
        nskey="dandi",
    )
    url: Optional[AnyUrl] = Field(
        None, readOnly=True, description="permalink to the item", nskey="schema"
    )
    repository: AnyUrl = Field(
        "https://dandiarchive.org/",
        readOnly=True,
        description="location of the item",
        nskey="dandi",
    )
    relatedResource: Optional[List[Resource]] = Field(None, nskey="dandi")

    wasGeneratedBy: Optional[Union[Activity, AnyUrl]] = Field(
        None, readOnly=True, nskey="prov"
    )


class DandiMeta(CommonModel):
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

    name: str = Field(
        title="Title",
        description="The name of the item.",
        max_length=150,
        nskey="schema",
    )

    description: str = Field(
        title="Description",
        description="A description of the item.",
        max_length=3000,
        nskey="schema",
    )
    contributor: List[Union[Person, Organization]] = Field(
        title="Contributors",
        description="Contributors to this item.",
        nskey="schema",
        min_items=1,
    )

    citation: str = Field(readOnly=True, nskey="schema")

    # From assets
    assetsSummary: AssetsSummary = Field(readOnly=True, nskey="dandi")

    # From server (requested by users even for drafts)
    manifestLocation: List[AnyUrl] = Field(readOnly=True, nskey="dandi")

    # On publish
    version: str = Field(readOnly=True, nskey="schema")
    doi: Optional[Union[str, AnyUrl]] = Field(None, readOnly=True, nskey="dandi")

    _ldmeta = {
        "rdfs:subClassOf": ["schema:Dataset", "prov:Entity"],
        "rdfs:label": "Information about the dataset",
        "nskey": "dandi",
    }


class PublishedDandiMeta(DandiMeta):
    publishedBy: AnyUrl = Field(
        description="The URL should contain the provenance of the publishing process.",
        readOnly=True,
        nskey="dandi",
    )  # TODO: formalize "publish" activity to at least the Actor
    datePublished: date = Field(readOnly=True, nskey="schema")


class AssetMeta(CommonModel):
    """Metadata used to describe an asset.

    Derived from C2M2 (Level 0 and 1) and schema.org
    """

    # Overrides CommonModel.license
    # TODO: https://github.com/NeurodataWithoutBorders/nwb-schema/issues/320
    license: Optional[List[License]] = Field(None, nskey="schema")

    contentSize: str = Field(nskey="schema")
    encodingFormat: Union[str, AnyUrl] = Field(nskey="schema")
    digest: Digest = Field(nskey="dandi")

    path: str = Field(None, nskey="dandi")

    # this is from C2M2 level 1 - using EDAM vocabularies - in our case we would
    # need to come up with things for neurophys
    # TODO: waiting on input <https://github.com/dandi/dandi-cli/pull/226>
    dataType: Optional[AnyUrl] = Field(None, nskey="dandi")

    sameAs: Optional[List[AnyUrl]] = Field(None, nskey="schema")

    # TODO
    modality: Optional[List[ModalityType]] = Field(None, readOnly=True, nskey="dandi")
    measurementTechnique: Optional[List[MeasurementTechniqueType]] = Field(
        None, readOnly=True, nskey="schema"
    )
    variableMeasured: Optional[List[PropertyValue]] = Field(
        None, readOnly=True, nskey="schema"
    )

    wasDerivedFrom: Optional[List[BioSample]] = Field(None, nskey="prov")

    # on publish or set by server
    contentUrl: Optional[List[AnyUrl]] = Field(None, readOnly=True, nskey="schema")

    _ldmeta = {
        "rdfs:subClassOf": ["schema:CreativeWork", "prov:Entity"],
        "rdfs:label": "Information about the asset",
        "nskey": "dandi",
    }


class PublishedAssetMeta(AssetMeta):
    publishedBy: AnyUrl = Field(
        description="The URL should contain the provenance of the publishing process.",
        readOnly=True,
        nskey="dandi",
    )  # TODO: formalize "publish" activity to at least the Actor
    datePublished: date = Field(readOnly=True, nskey="schema")
