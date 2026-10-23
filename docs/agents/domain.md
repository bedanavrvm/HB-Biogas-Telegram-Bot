# Domain docs

## Layout and reading order

This repository uses one shared documentation layout, not per-package copies
or a new `GLOSSARY-MAP.md`:

1. Read the root [AGENTS.md](../../AGENTS.md), including its domain glossary,
   instruction precedence, and workflow ownership guide. Read more specific
   `AGENTS.md` files when working in their directories.
2. Read [docs/glossary.md](../glossary.md) for the canonical shared vocabulary.
   The root [GLOSSARY.md](../../GLOSSARY.md) contains supplementary TAT and
   Origination terminology; it is not a replacement shared glossary.
3. Read decisions in [docs/adr/](../adr/) relevant to the proposed work. Follow
   their pointers to current runbooks or domain-specific references as needed.

Current code, catalogues, migrations, tests, and the repository's instruction
precedence still govern conflicts. Historical completion claims are not current
implementation evidence. Report a discovered terminology or ADR conflict rather
than silently choosing a convenient interpretation.

## Use and maintain the vocabulary

Use established terms in specifications, issue titles, tests, and explanations.
Preserve the distinction between independent workflow roles even when their
names match; consult the owning workflow's catalogue before reasoning about
authority.

Keep shared terminology changes in the existing shared glossary and maintain
the root AGENTS glossary as its instructions require. Keep narrowly scoped
supplementary terms in their existing document; avoid copying definitions into
these configuration files or inventing competing per-Mini-App glossaries.

If a needed concept is genuinely missing, raise it through domain modelling
and document the resolved meaning in the existing appropriate location. Missing
optional documentation is not a reason to scaffold a second documentation tree.

## Architecture decisions

Record structural decisions in the existing `docs/adr/` before implementation
when the repository's rules require it. Use its current naming and numbering
conventions. A proposal that contradicts an ADR must name the conflict and obtain
the required approval; installing or invoking a skill does not reopen settled
architecture, authorize a UI-standard migration, or enable production browser
access.
