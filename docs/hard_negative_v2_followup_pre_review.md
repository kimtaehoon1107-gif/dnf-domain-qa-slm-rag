# Hard-Negative v2 Follow-up Pre-review

This is an assistant pre-review, not human approval. The human decision fields in `data/review/hard_negative_blind_safe_v2_followup_10.csv` remain blank.

| source QA | recommended votes | rationale |
|---|---|---|
| `domain_train_0133` | yes / yes / yes | The candidates describe the general interface, configurable shortcuts, and chat commands; none states that `L` opens the friend menu. |
| `domain_train_0170` | yes / yes / yes | All candidates describe timeout rules for other named content. They do not answer the specified Asrahan Mu failure/recovery rule. |
| `domain_train_0171` | yes / yes / yes | The candidates discuss Bakal/Ozma rules or rewards, not Asrahan Mu's starting 15 coins and one-coin revival cost. |
| `domain_train_0186` | yes / yes / yes | Two candidates share the broad reward theme, but none states that higher required fame produces a higher expected reward multiplier. |
| `domain_train_0187` | yes / yes / yes | The candidates cover a Cheonhaecheon reward, another shop, and Gabriel. None states whether the Bannybu shop always appears after Cheonhaecheon. |
| `domain_train_0252` | yes / yes / yes | The candidates describe buffs in other raids or unrelated text; none provides Bakal's monster-kill acquisition fact or a grounded best-party recommendation. |
| `domain_train_0253` | yes / yes / yes | The candidates list exchange attributes, Bakal rewards, or equipment guidance; none explains NPC transcendence for moving untradeable equipment. |
| `domain_train_0256` | yes / yes / yes | The candidates list other rewards or selection boxes; none identifies Prime Stella's use for a Primordial general weapon selection box. |
| `casual_false_0001` | yes / yes / yes | The corrected row is answerable from the Bakal gold chunk. The candidates discuss other raids or an event and do not establish Bakal's weekly reward limit. |
| `casual_false_0017` | yes / yes / yes | The universal claim is now explicit: any box yielding the user's desired platinum emblem. The candidates describe specific packages or non-platinum selections and cannot support that guarantee. |

Recommended human decision for all ten rows is `approve`, but the reviewer should pay special attention to `domain_train_0186` and `casual_false_0017` because they are semantically close rather than obviously unrelated.
