---
name: datascrapper
description: 'Scrape football data from pasted page content and create a CSV containing only English Premier League data. Use when the user pastes raw page text or HTML and asks to extract structured match, table, fixture, or stats data while excluding other leagues.'
argument-hint: 'Pasted page content (raw text or HTML) and, optionally, desired CSV filename or columns'
user-invocable: true
---

# Premier League Scrape CSV

## What This Skill Does

This skill extracts structured football data from content pasted directly by the user and saves it as a CSV file containing only English Premier League rows.

It is designed for tasks where the user copies the full contents of a webpage and pastes it into the chat. The source may include multiple leagues, seasons, competitions, or mixed content, and the output must be narrowed to the English Premier League only.

## When to Use

- The user pastes raw page text or HTML from a football website and wants the data saved as CSV.
- The pasted content contains standings, fixtures, results, player stats, team stats, or match-level records.
- The source includes multiple leagues and the output must exclude all non-Premier-League data.
- The agent needs a repeatable extraction and validation workflow instead of ad hoc scraping.

## Required Inputs

- The full pasted contents of the page (raw text or HTML) containing the target data.

## Optional Inputs

- Desired CSV output path or filename.
- Requested columns or fixed schema.
- Season or date range.
- Page type to target, such as fixtures, results, table, or player stats.

## Default Behavior

- Infer the CSV columns from the source page unless the user explicitly requests a fixed schema.
- Scrape only the provided page by default.
- If expanding into tabs, pagination, linked seasons, or secondary pages may be useful, ask the user before doing so.

## Procedure

1. Confirm the pasted content.
If the user has not yet pasted the page contents, ask them to copy everything from the page and paste it into the chat.

2. Inspect the pasted content structure.
Identify whether the relevant data appears in HTML tables, repeated cards, embedded JSON, or plain text tabular data.

3. Determine the Premier League filter logic.
Use explicit indicators when available, such as:
- `Premier League`
- `English Premier League`
- `England: Premier League`
- competition, country, or league fields that clearly map to the top English league

If the page mixes competitions, define the exact filter before extracting all rows.

4. Extract structured records.
Prefer the most reliable machine-readable source in this order:
- embedded JSON within the pasted content
- semantic HTML tables
- stable repeated plain-text blocks

Avoid brittle parsing tied to presentation-only markup when a cleaner structure exists.

5. Normalize the dataset.
Trim whitespace, standardize column names, remove duplicate header rows, and convert obvious numeric or date fields into consistent string representations suitable for CSV export.

6. Keep only English Premier League rows.
Exclude all rows that do not unambiguously belong to the English Premier League.
If league membership is ambiguous, stop and ask the user whether to keep or discard borderline rows.

7. Validate the output before writing.
Check that:
- the CSV is not empty unless the source truly contains no Premier League data
- all retained rows satisfy the Premier League filter
- column names are consistent across all rows
- obvious duplicate records are removed if they came from pagination overlaps or repeated blocks

8. Write the CSV file.
Use the user-provided output filename if available. Otherwise choose a descriptive default such as `premier_league_data.csv`.

9. Report the result.
Summarize:
- content source (pasted by user)
- output file path
- row count
- columns written
- any assumptions, exclusions, or ambiguous cases

## Decision Rules

### If the Website Contains Multiple Competitions

- Prefer explicit league labels over inferring from team names.
- Do not merge Championship, FA Cup, EFL Cup, Champions League, or other English competitions into the output.
- If the page has season tabs or pagination, ask before expanding beyond the provided page.

### If the Pasted Content Appears Incomplete

- If the pasted content is clearly truncated or missing expected sections, ask the user to re-paste the full page contents.
- If the content appears to be the raw HTML source, parse it directly.
- If the content is plain text, infer tabular structure from spacing, delimiters, or repeated patterns.

### If Columns Are Inconsistent

- Preserve the shared core fields across rows.
- By default, infer a practical schema from the source page instead of forcing missing fields.
- Add sparse optional columns only when they are meaningful and stable.
- If the user needs a strict schema, ask for the required columns before finalizing.

### If No Premier League Rows Are Found

- Verify the filter once.
- Confirm whether the page actually covers Premier League data.
- Return a clear explanation instead of writing misleading output.

## Quality Checks

- The output contains only English Premier League records.
- The CSV can be opened as a normal tabular file.
- Headers are clear and normalized.
- Empty rows, duplicate header rows, and decorative content are excluded.
- The result summary states exactly what was scraped and filtered.

## Completion Criteria

The task is complete when:

- the source data has been inspected
- Premier League-only filtering has been applied
- the CSV has been written successfully
- the final response includes path, row count, and any important assumptions

## Example Prompts

- `/premier-league-scrape-csv` *(then paste the page contents when prompted)*
- `/premier-league-scrape-csv [paste page contents here] — save only Premier League rows to data/epl_table.csv`
- `/premier-league-scrape-csv Extract match results from this content for the 2024-25 English Premier League and create a CSV [paste page contents here]`