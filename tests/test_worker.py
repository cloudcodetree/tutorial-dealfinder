"""Saved searches & the periodic-suggestions worker (Part 33) over the snapshot.

Deterministic and offline: the worker searches the frozen snapshot with the same
retrieval + two-signal deal score the rest of the course uses, so the notified
item is the real hero-cast deal. The load-bearing assertions pin:

  1. first run surfaces the Anker Soundcore Q20i deal for the saved
     "noise cancelling headphones" search,
  2. a second run with the returned state emits nothing (idempotent),
  3. a newly-covered saved search triggers exactly one new notification.

No network, no email — delivery goes through the ConsoleNotifier stub.
"""
from dealfinder.worker import (
    ConsoleNotifier,
    Notifier,
    SavedSearch,
    SuggestionState,
    load_catalog,
    run_suggestions,
)

HERO_QUERY = "noise cancelling headphones"
ANKER_TITLE = "Anker Soundcore Q20i"


def _catalog():
    # Build once per test; offline, from the committed snapshot.
    return load_catalog()


def test_first_run_surfaces_the_anker_hero_deal():
    catalog = _catalog()
    saved = [SavedSearch(user_id="u1", query=HERO_QUERY, k=5)]
    notifier = ConsoleNotifier()

    notes, _ = run_suggestions(saved, SuggestionState(), catalog=catalog, notifier=notifier)

    # Exactly one new deal for the hero query, and it's the honest Anker Q20i.
    assert len(notes) == 1
    n = notes[0]
    assert ANKER_TITLE in n.title
    assert n.price == 44.99
    assert n.deal_score > 0.70  # the pinned +0.724 blended two-signal score
    # The notifier actually delivered it (dict payload recorded).
    assert notifier.sent == [n.as_dict()]


def test_second_run_with_updated_state_emits_nothing():
    catalog = _catalog()
    saved = [SavedSearch(user_id="u1", query=HERO_QUERY, k=5)]

    notes1, state1 = run_suggestions(saved, SuggestionState(), catalog=catalog)
    assert len(notes1) == 1

    # Feed the returned state back: the Anker is already seen → no re-notification.
    notes2, _ = run_suggestions(saved, state1, catalog=catalog)
    assert notes2 == []


def test_new_saved_search_triggers_exactly_one_new_notification():
    # Model a *newly appearing* deal as a newly-covered saved search: the user
    # already saw the headphones deal; they now also save "bluetooth speaker",
    # whose top result is a fresh deal the diff has never notified.
    catalog = _catalog()
    hp = SavedSearch(user_id="u1", query=HERO_QUERY, k=5)

    _, state = run_suggestions([hp], SuggestionState(), catalog=catalog)

    speaker = SavedSearch(user_id="u1", query="bluetooth speaker", k=1)
    notes, new_state = run_suggestions([hp, speaker], state, catalog=catalog)

    # The headphones deal is already seen; only the new speaker deal fires.
    assert len(notes) == 1
    assert notes[0].query == "bluetooth speaker"
    assert notes[0].deal_score >= 0.30

    # And it's now idempotent for both searches.
    notes3, _ = run_suggestions([hp, speaker], new_state, catalog=catalog)
    assert notes3 == []


def test_console_notifier_satisfies_the_protocol():
    # The stub is a structural Notifier (swap in email/push without touching diff).
    assert isinstance(ConsoleNotifier(), Notifier)


def test_state_copy_does_not_mutate_input_state():
    catalog = _catalog()
    saved = [SavedSearch(user_id="u1", query=HERO_QUERY, k=5)]
    original = SuggestionState()

    notes, new_state = run_suggestions(saved, original, catalog=catalog)

    assert len(notes) == 1
    # run_suggestions must not mutate the state it was handed (returns a new one).
    assert original.seen == {}
    assert new_state.seen != {}
