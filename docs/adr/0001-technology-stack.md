# ADR 0001 - Technology stack

- **Status:** Accepted
- **Date:** Sprint 1, Week 4
- **Deciders:** the whole team at the kick-off meeting

## Context

We have eight weeks and five part-time developers to deliver 20 core features.
The grading rubric weights the Scrum process, requirements traceability and
software quality at least as heavily as the finished product, and every member
must be able to explain any part of the code under questioning in Week 13.

Reading the product backlog, two things stand out. Nearly every one of the 53
user stories carries an access-control acceptance criterion. And two stories,
US-14.1 (prevent overlapping venue bookings) and US-18.3 (only one attendee
takes the last place), are concurrency problems rather than CRUD problems.

## Decision

Python 3.12 with Django 5 and Django REST Framework, PostgreSQL 16, and a React
18 + TypeScript single-page application built with Vite. Session cookie
authentication rather than JWT. A modular monolith, one Django app per
component, rather than services.

## Consequences

**Good.** Django ships users, roles and permissions, so the access-control
criteria are satisfied with permission classes rather than hand-written checks
repeated 53 times. PostgreSQL gives us an exclusion constraint for US-14.1 and
row-level locking for US-18.3, both correct under concurrency in a few lines.
Business logic sits in one language, so coverage is one number that maps onto
the traceability matrix. TypeScript catches drift between the API contract and
the UI at compile time.

**Bad.** Two languages and two test runners still means two CI jobs. The SPA
duplicates some validation rules that the API also enforces; the API remains the
authority and the client copy exists only to give faster feedback.

**Rejected.** Microservices, because five students over eight weeks cannot
absorb the integration cost and every boundary becomes a Week 10 failure.
MongoDB, because neither concurrency story above has a good document-database
answer. Next.js App Router, because its API has changed quickly and generated
code for it is more likely to follow outdated patterns, which is the wrong risk
when every line must be defensible.

## Follow-up

Sprint 3 needs the `btree_gist` PostgreSQL extension before the exclusion
constraint in US-14.1 can be added. Raise it during Sprint 2 refinement.
