import re
from dataclasses import dataclass

from app.core.errors import DomainError
from app.domain.enums import DiagnosticSeverity
from app.services.grammar.schemas import GrammarAnalysis, GrammarError
from app.services.knowledge_graph.graph import GrammarKnowledgeGraph

SENTENCE_PATTERN = re.compile(r"\S[^.!?]*(?:[.!?]|$)", re.DOTALL)
PAST_MARKER = re.compile(r"\b(?:yesterday|last night|last week|last year)\b", re.IGNORECASE)
SUBJECT_VERB = re.compile(
    r"\b(?P<subject>I|you|he|she|it|we|they)\s+"
    r"(?P<verb>go|goes|walk|walks|visit|visits|play|plays|see|sees|eat|eats|write|writes|do|does|make|makes|like|likes)\b",
    re.IGNORECASE,
)
PAST_FORMS = {
    "go": "went",
    "walk": "walked",
    "visit": "visited",
    "play": "played",
    "see": "saw",
    "eat": "ate",
    "write": "wrote",
    "do": "did",
    "make": "made",
    "like": "liked",
}
THIRD_SINGULAR = {
    "go": "goes",
    "walk": "walks",
    "visit": "visits",
    "play": "plays",
    "see": "sees",
    "eat": "eats",
    "write": "writes",
    "do": "does",
    "make": "makes",
    "like": "likes",
}
PRESENT_BASE = {value: key for key, value in THIRD_SINGULAR.items()}
MISSING_ARTICLE = re.compile(
    r"\b(?:saw|have|has|bought|found|is|was)\s+"
    r"(?P<noun>dog|cat|apple|book|teacher|student|idea|egg)\b",
    re.IGNORECASE,
)
WRONG_ARTICLE = re.compile(
    r"\b(?P<article>a|an)\s+(?P<noun>apple|book|dog|idea|egg)\b", re.IGNORECASE
)
FRAGMENT_PREFIX = re.compile(r"^(?P<prefix>Because|Although|When)\s+", re.IGNORECASE)
RUN_ON = re.compile(
    r"\b(?:I|he|she|they|we|you)\s+(?:like|likes|went|was|had|have|am|is|are)\b"
    r"[^.!?]*?(?P<join>\s+(?:I|he|she|they|we|you))\s+"
    r"(?:like|likes|went|was|had|have|am|is|are)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Candidate:
    start: int
    end: int
    replacement: str
    error_code: str
    category: str
    subtype: str
    reason: str
    confidence: float
    severity: DiagnosticSeverity
    structure_change: str


class GrammarAnalyzer:
    """Conservative deterministic diagnostics with KG linkage and no pedagogy decisions."""

    def __init__(self, graph: GrammarKnowledgeGraph) -> None:
        self.graph = graph

    def analyze(self, text: str) -> GrammarAnalysis:
        if not text.strip():
            return GrammarAnalysis(input_text=text, errors=[])
        errors: list[GrammarError] = []
        for sentence_match in SENTENCE_PATTERN.finditer(text):
            sentence = sentence_match.group()
            sentence_start = sentence_match.start()
            candidates = self._candidates(sentence)
            for candidate in candidates:
                node = self.graph.link_error(candidate.error_code)
                if node is None:
                    raise DomainError(
                        "grammar_node_missing",
                        f"No Knowledge Graph node for {candidate.error_code}",
                        500,
                    )
                corrected = (
                    sentence[: candidate.start] + candidate.replacement + sentence[candidate.end :]
                )
                original_structure = self._structure(sentence)
                corrected_structure = self._structure(corrected)
                errors.append(
                    GrammarError(
                        start_offset=sentence_start + candidate.start,
                        end_offset=sentence_start + candidate.end,
                        original_expression=sentence[candidate.start : candidate.end],
                        corrected_expression=candidate.replacement,
                        original_sentence=sentence,
                        corrected_sentence=corrected,
                        primary_category=candidate.category,
                        knowledge_node_id=node.id,
                        subtype=candidate.subtype,
                        original_structure=original_structure,
                        corrected_structure=corrected_structure,
                        structure_change=candidate.structure_change,
                        reason=candidate.reason,
                        confidence=candidate.confidence,
                        severity=candidate.severity,
                    )
                )
        return GrammarAnalysis(
            input_text=text, errors=sorted(errors, key=lambda item: item.start_offset)
        )

    def _candidates(self, sentence: str) -> list[Candidate]:
        candidates = (
            self._verb_candidates(sentence)
            + self._article_candidates(sentence)
            + self._structure_candidates(sentence)
        )
        candidates.sort(key=lambda item: (item.start, item.end, item.subtype))
        accepted: list[Candidate] = []
        for candidate in candidates:
            if not accepted or candidate.start >= accepted[-1].end:
                accepted.append(candidate)
        return accepted

    @staticmethod
    def _verb_candidates(sentence: str) -> list[Candidate]:
        candidates: list[Candidate] = []
        past_context = PAST_MARKER.search(sentence) is not None
        for match in SUBJECT_VERB.finditer(sentence):
            subject, verb = match.group("subject").casefold(), match.group("verb").casefold()
            base = PRESENT_BASE.get(verb, verb)
            start, end = match.span("verb")
            if past_context:
                replacement = PAST_FORMS.get(base)
                if replacement and verb != replacement:
                    candidates.append(
                        Candidate(
                            start,
                            end,
                            replacement,
                            "tense_error",
                            "verb",
                            "past_tense",
                            "The past-time marker requires a past verb form.",
                            0.9,
                            DiagnosticSeverity.MODERATE,
                            "Verb form changes; clause structure stays the same.",
                        )
                    )
            elif subject in {"he", "she", "it"} and verb == base:
                candidates.append(
                    Candidate(
                        start,
                        end,
                        THIRD_SINGULAR[base],
                        "sva",
                        "verb",
                        "subject_verb_agreement",
                        "A third-person singular subject requires a singular present verb.",
                        0.93,
                        DiagnosticSeverity.MODERATE,
                        "Verb inflection changes; clause structure stays the same.",
                    )
                )
            elif subject in {"i", "you", "we", "they"} and verb != base:
                candidates.append(
                    Candidate(
                        start,
                        end,
                        base,
                        "sva",
                        "verb",
                        "subject_verb_agreement",
                        "This subject requires the base present verb form.",
                        0.87,
                        DiagnosticSeverity.MODERATE,
                        "Verb inflection changes; clause structure stays the same.",
                    )
                )
        return candidates

    @staticmethod
    def _article_candidates(sentence: str) -> list[Candidate]:
        candidates: list[Candidate] = []
        for match in MISSING_ARTICLE.finditer(sentence):
            noun = match.group("noun")
            article = "an" if noun[0].casefold() in "aeiou" else "a"
            start, end = match.span("noun")
            candidates.append(
                Candidate(
                    start,
                    end,
                    f"{article} {noun}",
                    "article_error",
                    "word_classes",
                    "missing_article",
                    "A singular countable noun normally needs a determiner here.",
                    0.82,
                    DiagnosticSeverity.MODERATE,
                    "A determiner is added inside the noun phrase.",
                )
            )
        for match in WRONG_ARTICLE.finditer(sentence):
            article, noun = match.group("article"), match.group("noun")
            expected = "an" if noun[0].casefold() in "aeiou" else "a"
            if article.casefold() != expected:
                start, end = match.span("article")
                candidates.append(
                    Candidate(
                        start,
                        end,
                        expected,
                        "article_error",
                        "word_classes",
                        "a_an_choice",
                        "The article form should match the next word's initial sound in this case.",
                        0.86,
                        DiagnosticSeverity.MINOR,
                        "Article form changes; clause structure stays the same.",
                    )
                )
        return candidates

    @staticmethod
    def _structure_candidates(sentence: str) -> list[Candidate]:
        candidates: list[Candidate] = []
        prefix = FRAGMENT_PREFIX.match(sentence)
        if prefix and "," not in sentence:
            start, end = prefix.span()
            candidates.append(
                Candidate(
                    start,
                    end,
                    "",
                    "fragment",
                    "sentence_structure",
                    "dependent_fragment",
                    "A dependent clause is standing alone without a main clause.",
                    0.7,
                    DiagnosticSeverity.MAJOR,
                    "Dependent fragment becomes an independent clause.",
                )
            )
        run_on = RUN_ON.search(sentence)
        if run_on and "," not in sentence and ";" not in sentence:
            start, end = run_on.span("join")
            second_subject = run_on.group("join").strip()
            candidates.append(
                Candidate(
                    start,
                    end,
                    f". {second_subject}",
                    "run_on",
                    "sentence_structure",
                    "run_on",
                    "Two independent clauses need punctuation or a connector.",
                    0.78,
                    DiagnosticSeverity.MAJOR,
                    "Two independent clauses become separate sentences.",
                )
            )
        return candidates

    @staticmethod
    def _structure(sentence: str) -> str:
        if FRAGMENT_PREFIX.match(sentence) and "," not in sentence:
            return "dependent_clause_only"
        if RUN_ON.search(sentence) and "," not in sentence and ";" not in sentence:
            return "two_independent_clauses_without_connector"
        if sentence.count(". ") >= 1:
            return "two_simple_sentences"
        if re.search(r"\b(?:because|although|when)\b", sentence, re.IGNORECASE):
            return "complex_sentence"
        if re.search(r"\b(?:am|is|are|was|were)\b\s+\w+", sentence, re.IGNORECASE):
            return "subject_linking_predicative"
        if re.search(
            r"\b(?:saw|see|ate|eat|like|likes|wrote|write|have|has)\b\s+\w+",
            sentence,
            re.IGNORECASE,
        ):
            return "subject_verb_object"
        if SUBJECT_VERB.search(sentence):
            return "subject_predicate"
        return "undetermined"
