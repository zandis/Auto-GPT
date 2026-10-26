"""Boundary rules for data classes (spec v4 §7.1, §7.2; S1-01).

* :data:`CONTRACT_CLASSES` assigns every v1 contract (``tb_contracts`` model) the class of the data it carries.
  Labels are assigned at the source, never inferred by a model (§7.1).
* :func:`may_reach` answers whether data of a class may reach a destination under a topology. It is the single rule
  the gateway, the channels and the Test Bench consult; D3 and D4 never reach an external model in any topology.
* :func:`lower` is the only way to lower a class, through one of the four registered transforms, and it requires a
  certificate id.
"""

from __future__ import annotations

from enum import StrEnum

from tb_contracts.dataclass import ClassLabel, D2Variant, DataClass


class Topology(StrEnum):
    A = "A"  # on-prem appliance
    B = "B"  # hospital cloud tenant
    C = "C"  # hybrid: A or B plus model egress


class Destination(StrEnum):
    PERIMETER = "perimeter"  # process and store inside the site's own perimeter (box or attested tenant)
    TRE = "tre"  # the trusted research environment zone (Z-TRE)
    EXTERNAL_MODEL = "external_model"  # a vendor model endpoint outside the perimeter
    DEV_PUBLIC = "dev_public"  # developer / bake-off endpoints (OpenRouter and similar), Z-DEV


class Environment(StrEnum):
    DEV = "DEV"
    TEST = "TEST"
    VALIDATION = "VALIDATION"
    PRODUCTION = "PRODUCTION"


# highest class each environment may hold (§17.8)
ENV_CEILING: dict[Environment, DataClass] = {
    Environment.DEV: DataClass.D0,
    Environment.TEST: DataClass.D0,
    Environment.VALIDATION: DataClass.D2,
    Environment.PRODUCTION: DataClass.D4,
}


class PolicyError(PermissionError):
    """A class, boundary or certificate rule refused the operation (fail closed)."""


def may_reach(label: ClassLabel, dest: Destination, topology: Topology, *, cloud_opt_in: bool = False) -> bool:
    """§7.2 as code. ``cloud_opt_in`` is the site's explicit, contract-backed enablement of a D1/D2-L cloud route
    under topology C (default off); D0 needs none."""
    dc = label.data_class
    if dest == Destination.PERIMETER:
        return dc != DataClass.D2 or label.d2_variant != D2Variant.KEYED  # D2-K lives in Z-TRE only
    if dest == Destination.TRE:
        return dc in (DataClass.D0, DataClass.D1, DataClass.D2)
    if dest == Destination.DEV_PUBLIC:
        return dc == DataClass.D0 and not label.special_category
    # external model
    if dc in (DataClass.D3, DataClass.D4):
        return False
    if dc == DataClass.D0:
        return topology == Topology.C or cloud_opt_in
    if topology != Topology.C or not cloud_opt_in:
        return False
    if dc == DataClass.D2:
        return label.d2_variant == D2Variant.DELINKED and label.certificate is not None
    return True  # D1 under topology C with the opt-in


def check_env(label: ClassLabel, env: Environment) -> None:
    if label.data_class.rank > ENV_CEILING[env].rank:
        raise PolicyError(
            f"{label.tag} data is not allowed in the {env.value} environment (ceiling {ENV_CEILING[env]})"
        )


# ------------------------------------------------------------------------------------------------ declassification
TRANSFORMS: dict[str, tuple[DataClass, DataClass, D2Variant | None]] = {
    "privacy_accountant": (DataClass.D3, DataClass.D1, None),  # aggregate → released, privacy_ledger_entry
    "deid_pipeline_keyed": (DataClass.D3, DataClass.D2, D2Variant.KEYED),  # release_certificate
    "deid_pipeline_delinked": (DataClass.D3, DataClass.D2, D2Variant.DELINKED),
    "synthetic_twin": (DataClass.D2, DataClass.D2, D2Variant.DELINKED),
    "publication": (DataClass.D1, DataClass.D0, None),
}


def lower(label: ClassLabel, transform: str, certificate: str) -> ClassLabel:
    """Lower a class through a registered transform. Unknown transforms, a wrong input class or a missing
    certificate raise :class:`PolicyError`."""
    if transform not in TRANSFORMS:
        raise PolicyError(f"unregistered declassification transform {transform!r}")
    src, dst, variant = TRANSFORMS[transform]
    if label.data_class != src:
        raise PolicyError(f"{transform} lowers {src} only, got {label.tag}")
    if not certificate:
        raise PolicyError(f"{transform} needs a certificate id")
    return ClassLabel(
        data_class=dst, d2_variant=variant, special_category=label.special_category, certificate=certificate
    )


# ------------------------------------------------------------------------------------------------ v1 contracts
_D0 = {"CtgovSearchRequest", "CtgovSearchResult", "CtgovStudy", "TrialSimResult", "TrialSimRow", "TrialSimStep"}
_D1 = {
    # configuration, rule content, protocol-derived structures, job plumbing without patient data
    "AgeRange",
    "AtomValue",
    "Atom",
    "BoolExpr",
    "Duration",
    "Window",
    "CriterionIR",
    "CompileRequest",
    "CompileResult",
    "ConceptCandidate",
    "ConceptChoice",
    "CriterionReview",
    "DiffRequest",
    "DiffResult",
    "Disagreement",
    "ManifestReview",
    "ReviewDecision",
    "ApproveRequest",
    "ApproveResult",
    "RulesetManifest",
    "RulesetModels",
    "RulesetThresholds",
    "EquivalenceReport",
    "EquivalenceSummary",
    "ExtractedAtom",
    "ExtractedBool1",
    "ExtractedBool2",
    "ExtractedBool3",
    "ExtractedCriterion",
    "LlmExtractOutput",
    "LlmConceptMapOutput",
    "LlmIeLocateOutput",
    # consent explainer: built from the study's informed-consent form only, never from patient data
    "LlmConsentExplainOutput",
    "ConsentItem",
    "ConsentQuestion",
    "LlmConsentTranslateOutput",
    "ConsentItemText",
    "ConsentQuestionText",
    "LlmConsentVerifyOutput",
    "ConsentCheck",
    "ParseRequest",
    "ParsedDoc",
    "DocSection",
    "DocTable",
    "IEBlock",
    "PromptMeta",
    "ModelEntry",
    "ModelManifest",
    "UpdateFile",
    "UpdateManifest",
    "Settings",
    "SiteInfo",
    "Allowlist",
    "DataSource",
    "Profiles",
    "SiteModels",
    "SiteThresholds",
    "Schedule",
    "RegistrySource",
    "Retention",
    "CalibrationDefaults",
    "TwpasSettings",
    "CohortSettings",
    "Routing",
    "Scopes",
    "FeasScope",
    "NavScope",
    "ScreenScope",
    "ScreenRunScope",
    "CohortConfig",
    "Simulation",
    "JobError",
    "JobMetrics",
    "IngestRequest",
    "RebuildRequest",
    "RebuildResult",
    "EmbedRequest",
    "EmbedResponse",
    "TwpasConfig",
    "MissingItem",
    "Precheck",
    "ValidationSummary",
    "IngestReport",
    "JobCreate",
    "Job",
    # aggregates released after small-cell suppression
    "FeasibilityResult",
    "FunnelStep",
    "MonthlyCount",
    "SensitivityRow",
    "TierSummary",
    "CohortRow",
    "CohortTable",
}
_D3 = {
    "AuditEvent",
    "CandidateList",
    "CandidateRow",
    "ChunkHit",
    "ChunkSearchRequest",
    "ChunkSearchResult",
    "CriterionVerdict",
    "Evidence",
    "LakeQuery",
    "LlmJudgeOutput",
    "LlmDraftDocOutput",
    "NavLists",
    "NavListSet",
    "NavRow",
    "PatientEvaluation",
    "ScreenFeedback",
    "ScreenFeedbackRow",
    "JobFile",
    "JobOutput",
}
_D4 = {"SendRequest", "SendAttachment", "SendResult", "PractitionerInfo"}

CONTRACT_CLASSES: dict[str, DataClass] = {
    **dict.fromkeys(_D0, DataClass.D0),
    **dict.fromkeys(_D1, DataClass.D1),
    **dict.fromkeys(_D3, DataClass.D3),
    **dict.fromkeys(_D4, DataClass.D4),
}


def contract_class(name: str) -> DataClass:
    """Class of a v1 contract by model name; an unclassified contract raises (fail closed)."""
    try:
        return CONTRACT_CLASSES[name]
    except KeyError as e:
        raise PolicyError(f"contract {name!r} has no data class (add it to CONTRACT_CLASSES)") from e
