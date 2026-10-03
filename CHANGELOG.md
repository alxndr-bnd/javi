# Changelog

What changed in Javi for shops and their customers, version by version, newest first.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are the release
tags `vX.Y.Z`. Every entry has an English line and its Serbian (Latin script) translation right under it.
`changelog.py` parses this file for the release script, and `config/test_changelog.py` rejects anything else:

- `## [Unreleased]` stays on top. Write new entries there. The release script turns it into
  `## [X.Y.Z] - YYYY-MM-DD` (see "Releasing" in the README) and refuses to release without entries.
- Sections: `### Added`, `### Changed`, `### Fixed`, `### Security`.
- An entry is one line `- English text`, followed by one line `  - SR: Srpski tekst` (Latin script).
- Write for shops: what they can now do or what got fixed. 1–5 short lines per release, no ticket numbers.

## [Unreleased]

### Security
- The landing page and the privacy page can no longer be embedded in another site's frame. This protects the sign-up form from clickjacking.
  - SR: Početna stranica i stranica o privatnosti više ne mogu da se ugrade u okvir drugog sajta. Ovo štiti formular za prijavu od clickjacking napada.

## [0.70.0] - 2026-10-03

### Security
- The app now gets operating-system security fixes every week, even between releases.
  - SR: Aplikacija sada svake nedelje dobija bezbednosne ispravke operativnog sistema, i između izdanja.

## [0.69.0] - 2026-10-03

### Security
- The server image gets Debian security fixes every day and no longer contains build tools it does not need.
  - SR: Serverska slika svakog dana dobija bezbednosne ispravke za Debian i više ne sadrži alate za izgradnju koji joj nisu potrebni.
- The release pipeline checks its security scanner against a fixed checksum and keeps the access token out of the code checkout.
  - SR: Proces objavljivanja proverava skener bezbednosti prema fiksnom kontrolnom zbiru i ne čuva pristupni token u preuzetom kodu.

## [0.68.0] - 2026-10-02

### Added
- Shops can edit a delivery until it is delivered. Sign-up asks for the store address, and "Save and notify now" sends the first notification in one step.
  - SR: Prodavnice mogu da izmene dostavu sve dok ne bude isporučena. Pri registraciji se unosi adresa prodavnice, a „Sačuvaj i obavesti odmah“ šalje prvo obaveštenje u jednom koraku.

### Changed
- Customers get SMS messages and the tracking page in their own language. The Serbian interface is fully in Latin script.
  - SR: Kupci dobijaju SMS poruke i stranicu za praćenje na svom jeziku. Srpski interfejs je u potpunosti na latinici.

### Fixed
- A double click on "Confirm and notify" sends one SMS. A past delivery time is refused, and customers can rate only delivered orders.
  - SR: Dvostruki klik na „Potvrdi i obavesti“ šalje jedan SMS. Vreme dostave u prošlosti se odbija, a kupci mogu da ocene samo isporučene porudžbine.

## [0.67.0] - 2026-10-02

### Fixed
- When you return to the browser window, the landing page no longer scrolls under the cookie banner.
  - SR: Kada se vratite u prozor pregledača, početna stranica se više ne pomera ispod banera za kolačiće.

## [0.66.0] - 2026-10-01

### Changed
- The cookie banner shows "Accept" and "Decline" with equal weight.
  - SR: Baner za kolačiće prikazuje „Prihvati“ i „Odbij“ ravnopravno.

### Fixed
- The contact form and sign-up fill in the store name automatically, and form fields have visible borders.
  - SR: Kontakt forma i registracija automatski popunjavaju naziv prodavnice, a polja forme imaju vidljive ivice.

## [0.65.0] - 2026-09-30

### Fixed
- The tracking page works with screen readers, and the Tab key moves from left to right. The cookie banner never hides the focused element.
  - SR: Stranica za praćenje radi sa čitačima ekrana, a taster Tab ide sleva nadesno. Baner za kolačiće nikada ne skriva element u fokusu.

## [0.64.0] - 2026-09-29

### Added
- Trial stores see how to get verified. Sign-ups and API keys have limits.
  - SR: Prodavnice na probnom periodu vide kako da prođu verifikaciju. Registracije i API ključevi imaju ograničenja.

### Security
- Sign-in locks after too many failed attempts. Secrets no longer appear in links or logs.
  - SR: Prijava se zaključava posle previše neuspešnih pokušaja. Tajni podaci se više ne pojavljuju u linkovima ni u logovima.

[Unreleased]: https://github.com/alxndr-bnd/javi/compare/v0.70.0...HEAD
[0.70.0]: https://github.com/alxndr-bnd/javi/compare/v0.69.0...v0.70.0
[0.69.0]: https://github.com/alxndr-bnd/javi/compare/v0.68.0...v0.69.0
[0.68.0]: https://github.com/alxndr-bnd/javi/compare/v0.67.0...v0.68.0
[0.67.0]: https://github.com/alxndr-bnd/javi/compare/v0.66.0...v0.67.0
[0.66.0]: https://github.com/alxndr-bnd/javi/compare/v0.65.0...v0.66.0
[0.65.0]: https://github.com/alxndr-bnd/javi/compare/v0.64.0...v0.65.0
[0.64.0]: https://github.com/alxndr-bnd/javi/releases/tag/v0.64.0
