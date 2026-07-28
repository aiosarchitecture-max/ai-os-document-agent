# Smernica AI_OS: Research-first riešenie problémov

**Stav:** záväzná  
**Platnosť:** pre všetkých ľudí, agentov a subagentov pracujúcich na AI_OS  
**Účel:** minimalizovať pokusy, opakované zásahy a neoverené riešenia.

## Záväzné pravidlo

Pri každom probléme alebo náznaku problému musí riešiteľ postupovať v tomto poradí:

1. **Najprv vyhľadať existujúce funkčné riešenia.** Urobiť rešerš v oficiálnej dokumentácii, overených implementáciách, issue trackeroch a relevantných technických zdrojoch.
2. **Overiť použiteľnosť pre AI_OS.** Skontrolovať aktuálnosť, verziu, bezpečnosť a zhodu s konkrétnym kódom, konfiguráciou a prostredím AI_OS.
3. **Skontrolovať skutočný stav systému.** Pred zásahom porovnať názvy premenných, endpointy, vetvu, nasadenú verziu a zdroj pravdy. Záver nesmie stáť iba na predpoklade.
4. **Riešenie najprv bezpečne nasimulovať alebo otestovať.** Test nesmie meniť živé dáta, odhaľovať tajomstvá ani vyžadovať opakované manuálne zásahy používateľa, ak sa tomu dá vyhnúť.
5. **Predložiť jeden ucelený zásah.** Používateľ dostane presný, overený postup spolu s očakávaným výsledkom a bezpečným spôsobom kontroly.
6. **Vlastné riešenie vytvárať až ako poslednú možnosť.** Návrh „na zelenej lúke“ je prípustný iba po preukázaní, že neexistuje kompatibilné a použiteľné riešenie.

## Kritériá dôkazu

Riešenie možno označiť za overené iba vtedy, keď je podložené aspoň:

- autoritatívnym alebo primárnym zdrojom,
- kontrolou kompatibility s AI_OS,
- reprodukovateľným testom alebo bezpečnou simuláciou,
- jasnými podmienkami úspechu a návratu späť.

## Zakázané postupy

- séria pokusov na živom systéme bez predchádzajúcej rešerše,
- opakovanie rovnakého neúspešného kroku bez nového dôkazu,
- vydávanie hypotézy za potvrdenú príčinu,
- požadovanie ďalšieho manuálneho zásahu od používateľa pred kontrolou kódu, konfigurácie a dostupných zdrojov,
- vkladanie tajomstiev do zdrojového kódu, logov, chatu alebo snímok obrazovky.

## Povinný výstup pri riešení problému

Každý návrh zásahu musí stručne uviesť:

1. potvrdenú príčinu alebo jasne označenú hypotézu,
2. zdroj alebo dôkaz,
3. výsledok simulácie či testu,
4. presný zásah,
5. očakávaný výsledok a spôsob jeho overenia.

Skrátené operačné pravidlo AI_OS:

> **Najprv rešerš → potom kontrola reality → overenie a simulácia → jeden presný zásah → vlastný návrh až ako posledná možnosť.**
