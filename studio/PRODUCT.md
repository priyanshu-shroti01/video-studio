# Product

Product context for the local Video Studio web app (`studio/`). Facts marked *(inferred)* come from the brief and
docs/PRODUCT_PLAN.md, not from an interview.

## Platform

web

## Stack

Python stdlib server (`studio/server.py`), React + TypeScript built with esbuild (`studio/web/src`), one stylesheet
(`studio/web/src/styles.css`) with the design tokens. Runs on the user's Mac at `http://127.0.0.1:<port>/`; no network at
runtime (fonts and icons are vendored).

## Users

Non-technical marketers who run one or more websites (brands) and need short product videos for social channels.
They compare the Studio with paid SaaS video tools. Power users (the owner, a developer) also use the Advanced pages.

## Product Purpose

Turn a product brief into an approved video: pick a website, say what to promote, pick one of three ideas, review the
storyboard preview, make the video, approve it, download and post it.

## Positioning

Local and free: everything runs on the user's Mac, prices and claims come only from the website's checked facts, and a
named person approves the preview and the final video. Nothing is posted automatically.

## Operating Context

Operate mode: a tool people return to several times a week, often while a render runs in the background. Long tasks
(ideas, preview, render) take from a minute to several minutes. *(inferred)*

## Capabilities and Constraints

- Every step calls the same pipeline API as the CLI; the UI cannot skip validation, the preview review or approval.
- Approval needs a typed name; publishing needs a typed confirmation. The UI never approves or posts by itself.
- Strict CSP: scripts, styles, fonts and images only from the Studio itself.

## Brand Commitments

Tone: calm, precise, trustworthy. Plain words over pipeline terms (ids stay in small muted text). No hype, no emoji.
Visual: dark, flat, mostly monochrome; one sky-blue accent for focus, the active page and links; a light primary
button; status shown as a small badge with a coloured dot.

## Evidence on Hand

Real productions and their stills under `output/`; the brands' logos and colours under `public/brands/`.

## Product Principles

1. One clear next step per screen (the 1-to-3 rule: one primary action, at most three secondary ones).
2. Show the real thing: thumbnails are real stills, numbers are real (no vanity stats).
3. Say what happened and what to do next in every empty, loading and error state.
4. A person decides; the Studio prepares.

## Accessibility & Inclusion

Keyboard first (number keys switch pages, visible focus ring), text contrast at least 4.5:1, nothing under 13px,
sentence case, reduced motion respected.
