// In-process CQL evaluation for tools/cql_eval.py (T-504, D-321): the clinical-reasoning LibraryEngine that HAPI FHIR
// 8.12 runs behind Library/$evaluate, over an in-memory repository instead of a FHIR server. Run with the jars of
// pom.xml on the class path (java -cp ... CqlLocal.java). Arguments: see main().
import ca.uhn.fhir.context.FhirContext;
import ca.uhn.fhir.parser.IParser;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.*;
import org.hl7.elm.r1.VersionedIdentifier;
import org.hl7.fhir.instance.model.api.IBaseParameters;
import org.hl7.fhir.instance.model.api.IBaseResource;
import org.hl7.fhir.r4.model.*;
import org.opencds.cqf.fhir.cql.EvaluationSettings;
import org.opencds.cqf.fhir.cql.LibraryEngine;
import org.opencds.cqf.fhir.cql.engine.retrieve.RetrieveSettings;
import org.opencds.cqf.fhir.cql.engine.terminology.TerminologySettings;
import org.opencds.cqf.fhir.utility.repository.InMemoryFhirRepository;

public class CqlLocal {
  public static void main(String[] a) throws Exception {
    // a[0] resources (NDJSON: patients' resources, ValueSets, Libraries), a[1] library name, a[2] library version,
    // a[3] index date, a[4] expressions (comma), a[5] patient ids file (one per line), a[6] output NDJSON
    FhirContext ctx = FhirContext.forR4Cached();
    IParser json = ctx.newJsonParser();
    InMemoryFhirRepository repo = new InMemoryFhirRepository(ctx);
    for (String line : Files.readAllLines(Path.of(a[0]), StandardCharsets.UTF_8)) {
      if (!line.isBlank()) repo.update((IBaseResource) json.parseResource(line), Map.of());
    }
    EvaluationSettings settings = EvaluationSettings.Companion.getDefault();
    settings.getRetrieveSettings()
        .setSearchParameterMode(RetrieveSettings.SEARCH_FILTER_MODE.FILTER_IN_MEMORY)
        .setTerminologyParameterMode(RetrieveSettings.TERMINOLOGY_FILTER_MODE.FILTER_IN_MEMORY)
        .setProfileMode(RetrieveSettings.PROFILE_MODE.OFF);
    settings.getTerminologySettings()
        .setValuesetExpansionMode(TerminologySettings.VALUESET_EXPANSION_MODE.PERFORM_NAIVE_EXPANSION)
        .setValuesetMembershipMode(TerminologySettings.VALUESET_MEMBERSHIP_MODE.USE_EXPANSION)
        .setValuesetPreExpansionMode(TerminologySettings.VALUESET_PRE_EXPANSION_MODE.USE_IF_PRESENT);
    LibraryEngine engine = new LibraryEngine(repo, settings);
    VersionedIdentifier id = new VersionedIdentifier().withId(a[1]).withVersion(a[2]);
    Set<String> exprs = new LinkedHashSet<>(Arrays.asList(a[4].split(",")));
    StringBuilder out = new StringBuilder();
    for (String pid : Files.readAllLines(Path.of(a[5]), StandardCharsets.UTF_8)) {
      if (pid.isBlank()) continue;
      Parameters p = new Parameters();
      p.addParameter().setName("IndexDate").setValue(new DateType(a[3]));
      IBaseParameters r = engine.evaluate(id, "Patient/" + pid.strip(), p, null, null, null, exprs);
      Parameters res = (Parameters) r;
      res.setId(pid.strip());
      out.append(json.encodeResourceToString(res)).append('\n');
    }
    Files.writeString(Path.of(a[6]), out.toString(), StandardCharsets.UTF_8);
  }
}
