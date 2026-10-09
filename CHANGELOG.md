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

### Changed
- The home page now has a short "What is Javi" summary, a "Why Javi" section with a comparison to other kinds of delivery tools, and more answers to common questions.
  - SR: Početna stranica sada ima kratak opis „Šta je Javi“, odeljak „Zašto Javi“ sa poređenjem sa drugim vrstama alata za dostavu i više odgovora na česta pitanja.

## [0.79.0] - 2026-10-09

### Changed
- The home page now shows who Javi is for, how it works in 3 steps, the price, common questions and who runs Javi. The price is 30 € a month with Viber and SMS messages included. The first 30 days are free. After that, payment is required to continue; without it, the trial limits stay.
  - SR: Početna stranica sada pokazuje za koga je Javi, kako radi u 3 koraka, cenu, česta pitanja i ko stoji iza Javija. Cena je 30 € mesečno, a Viber i SMS poruke su uključene. Prvih 30 dana je besplatno. Posle toga je za nastavak potrebno plaćanje; bez njega ostaju probni limiti.
- The contact form is shorter: shop name, contact and an optional message.
  - SR: Forma za kontakt je kraća: naziv prodavnice, kontakt i opciona poruka.
- The home page shows the message a customer gets and the tracking page (test data).
  - SR: Početna stranica pokazuje poruku koju kupac dobija i stranicu za praćenje (test podaci).
- The site has its own icon files for browsers and phone home screens.
  - SR: Sajt ima sopstvene ikonice za pregledače i početni ekran telefona.

### Fixed
- The tracking page shows the first step as "Primljeno" in Serbian, not "Received".
  - SR: Stranica za praćenje prikazuje prvi korak kao „Primljeno“ na srpskom, a ne „Received“.

## [0.78.0] - 2026-10-08

### Security
- Customer names, phone numbers and addresses are now deleted 90 days after a delivery is finished. Delivery status, ratings and dates stay. Customers who unsubscribed still get no messages.
  - SR: Imena, brojevi telefona i adrese kupaca sada se brišu 90 dana posle završetka dostave. Status dostave, ocene i datumi ostaju. Kupci koji su se odjavili i dalje ne dobijaju poruke.

## [0.77.0] - 2026-10-05

### Changed
- Search results now show Javi with a short description of what it does: Viber/SMS delivery notifications. Google also gets structured facts about the app and who makes it.
  - SR: Rezultati pretrage sada prikazuju Javi sa kratkim opisom: Viber/SMS obaveštenja o isporuci. Google dobija i strukturisane podatke o aplikaciji i o tome ko je pravi.

## [0.76.0] - 2026-10-05

### Changed
- The home page now has its own address for each language: Serbian at javi.serbito.rs, English at /en/ and Russian at /ru/. Google can now show the Serbian page to people who search in Serbian.
  - SR: Početna stranica sada ima posebnu adresu za svaki jezik: srpski na javi.serbito.rs, engleski na /en/ i ruski na /ru/. Google sada može da prikaže srpsku stranicu onima koji pretražuju na srpskom.

## [0.75.0] - 2026-10-05

### Security
- Javi now runs under its own Google Cloud account that can read only Javi's settings, so a fault in another service cannot reach them.
  - SR: Javi sada radi pod sopstvenim Google Cloud nalogom koji može da čita samo Javi podešavanja, pa greška u drugom servisu ne može da dođe do njih.

## [0.74.0] - 2026-10-05

### Security
- Requests to the direct Cloud Run address now go to javi.serbito.rs, so the site's edge protection always applies.
  - SR: Zahtevi na direktnu Cloud Run adresu sada idu na javi.serbito.rs, pa zaštita sajta na ulazu uvek radi.

## [0.73.0] - 2026-10-04

### Security
- Sign-in and sign-up limits now count each visitor by their real address, also behind the Cloudflare proxy, and ignore forged address headers.
  - SR: Ograničenja prijave i registracije sada broje svakog posetioca po njegovoj stvarnoj adresi, i iza Cloudflare proksija, i ignorišu lažna zaglavlja sa adresom.

## [0.72.0] - 2026-10-03

### Security
- Python is updated to 3.14.8 with current security fixes.
  - SR: Python je ažuriran na 3.14.8 sa najnovijim bezbednosnim ispravkama.

## [0.71.0] - 2026-10-03

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

[Unreleased]: https://github.com/alxndr-bnd/javi/compare/v0.79.0...HEAD
[0.79.0]: https://github.com/alxndr-bnd/javi/compare/v0.78.0...v0.79.0
[0.78.0]: https://github.com/alxndr-bnd/javi/compare/v0.77.0...v0.78.0
[0.77.0]: https://github.com/alxndr-bnd/javi/compare/v0.76.0...v0.77.0
[0.76.0]: https://github.com/alxndr-bnd/javi/compare/v0.75.0...v0.76.0
[0.75.0]: https://github.com/alxndr-bnd/javi/compare/v0.74.0...v0.75.0
[0.74.0]: https://github.com/alxndr-bnd/javi/compare/v0.73.0...v0.74.0
[0.73.0]: https://github.com/alxndr-bnd/javi/compare/v0.72.0...v0.73.0
[0.72.0]: https://github.com/alxndr-bnd/javi/compare/v0.71.0...v0.72.0
[0.71.0]: https://github.com/alxndr-bnd/javi/compare/v0.70.0...v0.71.0
[0.70.0]: https://github.com/alxndr-bnd/javi/compare/v0.69.0...v0.70.0
[0.69.0]: https://github.com/alxndr-bnd/javi/compare/v0.68.0...v0.69.0
[0.68.0]: https://github.com/alxndr-bnd/javi/compare/v0.67.0...v0.68.0
[0.67.0]: https://github.com/alxndr-bnd/javi/compare/v0.66.0...v0.67.0
[0.66.0]: https://github.com/alxndr-bnd/javi/compare/v0.65.0...v0.66.0
[0.65.0]: https://github.com/alxndr-bnd/javi/compare/v0.64.0...v0.65.0
[0.64.0]: https://github.com/alxndr-bnd/javi/releases/tag/v0.64.0
