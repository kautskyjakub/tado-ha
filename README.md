# tado-ha — lokální rozšíření pro tado X v Home Assistant

Vlastní Home Assistant integrace + Lovelace karta, která nad **lokálně** ovládaným
termostatem *tado X* (přes vestavěnou Matter integraci HA) dodává funkce, které
tado normálně řeší přes svůj cloud: vizuální týdenní rozvrh, teplotu v režimu
*pryč*, *eco mode*, vytápění podle předpovědi počasí a probouzecí čas podle
budíku na Garmin hodinkách. **Žádný účet tado° ani cloud tado° se nepoužívá.**

## Proč to takhle vypadá (přečti si to dřív, než začneš)

*tado X* komunikuje lokálně výhradně přes **Matter/Thread** — žádné skryté
HTTP API na bridge, ke kterému by šlo přistoupit, neexistuje (na rozdíl od
staršího *V3/V3+* s Internet Bridge). Home Assistant už dnes umí *tado X*
napojit čistě lokálně přes svou vestavěnou Matter integraci, ale Matter u
tohoto zařízení vystavuje jen: aktuální teplotu, topný/vypnutý režim a
setpoint. *Eco mode*, *rozvrh* a *geofencing*, jak je zná appka tado°, jsou
pojmy z cloudové logiky tado° a fyzicky nejdou přečíst ani nastavit lokálně —
geofencing navíc vyžaduje GPS polohu telefonu, která u samotného termostatu
vůbec nevzniká.

**Řešení zvolené v této větvi:** eco mode, rozvrh i "chytré" probouzení jsou
znovu vytvořené jako vlastní logika v Home Assistantu, která řídí standardní
`climate.*` entitu poskytnutou Matter integrací. Vizuálně a funkčně se to
chová podobně jako tado° appka, ale běží to celé lokálně u tebe doma.

## Co to umí

- **Kruhový ovládací panel termostatu** — stejná interakce jako u běžné HA
  termostat karty (tažení po kruhu + zobrazení aktuální/cílové teploty).
- **Vizuální týdenní rozvrh** — malování režimů *Comfort / Eco / Off* po
  30minutových blocích pro každý den zvlášť, stejně jako tado° "Smart Schedule".
- **Teplota v režimu pryč** (*away temperature*) — vlastní číslo, upravitelné
  přímo z karty i z HA UI.
- **Eco mode** — přepínač, který odečte nastavený "setback" (výchozí 2 °C) od
  aktuálně platného bloku rozvrhu.
- **Vytápění podle předpovědi počasí** — před každým přechodem do "Comfort"
  bloku se topení spustí s předstihem, který se počítá z rozdílu aktuální a
  cílové teploty a z toho, jak chladno má být venku (viz níže).
- **Probouzení podle budíku z Garmin hodinek** — pokud zadáš přihlašovací
  údaje do Garmin Connect, ranní "Comfort" blok pro daný den se automaticky
  posune na čas tvého nejbližšího aktivního budíku.
- **Probouzení podle čidla v jiné místnosti** (např. ThermoPro v ložnici) —
  volitelné, viz sekce níže. Termostat zůstává v obýváku, ale cílová teplota
  a "kdy už je dost teplo" se vyhodnocuje podle čidla v ložnici.
- **Topná sezóna** — mimo nastavené měsíce (výchozí říjen–duben) se aktivně
  netopí vůbec, jen běží mrazová pojistka. Chladná noc mimo sezónu tak nic
  nespustí — rozhoduje kalendář, ne okamžitá teplota.
- **"Mírný den"** — uvnitř sezóny, když venku (aktuálně/dle předpovědi)
  přesáhne nastavenou hranici, se cílová teplota automaticky sníží (podobně
  jako eco mode), protože byt se pravděpodobně dohřeje sám. Viz sekce níže.

## Architektura

```
Garmin Connect (garminconnect knihovna, nepovinné)
        │  budíky (polling ~30 min)
        ▼
┌─────────────────────────────┐        ┌──────────────────────────┐
│ custom_components/          │        │ www/tado-schedule-card/  │
│ tado_schedule/               │◄──────►│ tado-schedule-card.js    │
│  - schedule_store.py (JSON)  │services│ (vlastní Lovelace karta) │
│  - decision.py (výpočet cíle)│        └──────────────────────────┘
│  - coordinator.py (tick 5min)│
└──────────────┬────────────────┘
               │ climate.set_temperature / set_hvac_mode
               ▼
   climate.<tvůj_tado_x_matter_entity>   (lokální Matter integrace HA)
```

## Instalace

### 1. Integrace (`custom_components/tado_schedule`)

1. Zkopíruj složku `custom_components/tado_schedule` do `<config>/custom_components/`
   ve tvé Home Assistant instalaci (nebo přidej tento repozitář jako vlastní
   zdroj v HACS a nainstaluj "Tado Schedule (local, Matter-based)").
2. Restartuj Home Assistant.
3. **Settings → Devices & services → Add integration → "Tado Schedule"**.
4. Vyplň formulář:
   - **Zone name** — libovolný název místnosti.
   - **Thermostat entity** — vyber `climate.*` entitu, kterou ti *tado X*
     vytvořil přes Matter integraci.
   - **Weather entity** — nepovinné, entita `weather.*` pro predikci vytápění.
   - **Wake sensor** — nepovinné, entita `sensor.*` s `device_class: temperature`
     (např. tvůj ThermoPro v ložnici), viz sekce
     [Probouzení podle čidla v jiné místnosti](#probouzení-podle-čidla-v-jiné-místnosti-thermopro).
   - **Garmin Connect email/password** — nepovinné, pro synchronizaci budíku.
5. Po dokončení vznikne zařízení s několika entitami (viz níže) — najdeš je
   pod **Settings → Devices & services → Devices → <Zone name>**.

> **Garmin poznámka:** knihovna `garminconnect` je neoficiální (reverse
> engineered) klient Garmin Connect. Formát budíků se v čase mírně měnil,
> takže parsování v `garmin.py` je záměrně tolerantní — pokud se u tebe po
> instalaci `sensor.<zone>_next_garmin_wake` neplní, zapni si v HA logu debug
> level pro `custom_components.tado_schedule.garmin` a podívej se, jaké klíče
> tvůj účet reálně vrací (`_LOGGER.debug` to vypíše), a uprav `_parse_alarm`.

### 2. Karta (`www/tado-schedule-card`)

1. Zkopíruj `www/tado-schedule-card/tado-schedule-card.js` do
   `<config>/www/tado-schedule-card/tado-schedule-card.js`.
2. **Settings → Dashboards → ⋮ → Resources → Add resource**:
   - URL: `/local/tado-schedule-card/tado-schedule-card.js`
   - Type: JavaScript module
3. Přidej kartu do dashboardu (YAML mód nebo "Manual card"):

```yaml
type: custom:tado-schedule-card
config_entry_id: "<vlož entry_id integrace, viz URL na stránce zařízení>"
climate_entity: climate.obyvak
eco_switch: switch.obyvak_eco_mode
away_switch: switch.obyvak_away_mode
away_number: number.obyvak_away_temperature
weekplan_sensor: sensor.obyvak_weekplan
next_change_sensor: sensor.obyvak_next_schedule_change
next_garmin_sensor: sensor.obyvak_next_garmin_wake
min_temp: 10
max_temp: 28
```

`config_entry_id` najdeš v URL stránky daného zařízení
(`.../config/integrations/config_entry/<toto_je_entry_id>`).

## Entity, které integrace vytvoří

| Entita | Typ | Co dělá |
|---|---|---|
| `number.<zone>_away_temperature` | number | cílová teplota v režimu pryč |
| `number.<zone>_eco_setback` | number | o kolik °C eco mode sníží aktuální blok |
| `number.<zone>_warmup_minutes_per_degree` | number | rychlost ohřevu tvé místnosti (min/°C) |
| `number.<zone>_max_preheat_minutes` | number | strop na předstih vytápění |
| `number.<zone>_outdoor_baseline_temp` | number | venkovní teplota, od které se předstih začíná prodlužovat |
| `number.<zone>_outdoor_sensitivity` | number | jak moc chlad venku prodlužuje předstih |
| `number.<zone>_wake_ready_buffer_minutes` | number | kolik minut před budíkem/blokem má být už teplo |
| `number.<zone>_wake_target_temperature` | number | cílová teplota **na wake sensoru** (např. 24 °C v ložnici) |
| `number.<zone>_wake_boost_temperature` | number | jak vysoko se nastaví termostat v obýváku, aby jistě topil, dokud wake sensor nedosáhne cíle |
| `number.<zone>_heating_season_start_month_1_12` / `..._heating_season_end_month_1_12` | number | 1–12, měsíce topné sezóny (výchozí 10 a 4 = říjen–duben, přes přelom roku) |
| `number.<zone>_frost_protection_floor_outside_season` | number | bezpečnostní minimum mimo sezónu (výchozí 7 °C) |
| `number.<zone>_mild_day_outdoor_threshold` | number | venkovní teplota, nad kterou se počítá s "mírným dnem" (výchozí 16 °C) |
| `number.<zone>_mild_day_setback` | number | o kolik °C se sníží cílovka v mírný den (výchozí 3 °C) |
| `switch.<zone>_eco_mode` | switch | zapíná/vypíná eco setback |
| `switch.<zone>_away_mode` | switch | přepne na teplotu "pryč" |
| `sensor.<zone>_current_decision` | sensor | proč se topí/netopí právě teď (`scheduled comfort`, `preheating for 06:30`, `away`, ...) |
| `sensor.<zone>_next_schedule_change` | sensor | čas dalšího přechodu v rozvrhu |
| `sensor.<zone>_next_garmin_wake` | sensor | čas nejbližšího aktivního Garmin budíku |
| `sensor.<zone>_weekplan` | sensor | surový týdenní rozvrh v atributu `weekplan` (čte ho karta) |
| `button.<zone>_sync_garmin_now` | button | okamžitě obnoví budíky z Garminu |

Services: `tado_schedule.set_schedule`, `tado_schedule.get_schedule`,
`tado_schedule.sync_garmin_now` (viz `services.yaml`).

## Jak funguje predikce vytápění (a proč je to heuristika)

Nejde nijak lokálně zjistit skutečnou tepelnou setrvačnost tvého pokoje, takže
`decision.py` používá jednoduchý, ale nastavitelný odhad:

$$\text{předstih (min)} = \min\big(\text{max\_preheat\_minutes},\; (T_{cíl} - T_{aktuální}) \times \text{warmup\_minutes\_per\_degree} \times (1 + \max(0, T_{baseline} - T_{venku}) \times \text{outdoor\_sensitivity})\big)$$

Zjednodušeně: čím větší je rozdíl mezi aktuální a cílovou teplotou a čím
chladněji má být venku, tím dřív se začne topit — všechny čtyři konstanty
(`warmup_minutes_per_degree`, `max_preheat_minutes`, `outdoor_baseline_temp`,
`outdoor_sensitivity`) jsou `number` entity, které si doladíš přímo v HA podle
reálného chování tvé místnosti, bez zásahu do kódu.

## Probouzení podle čidla v jiné místnosti (ThermoPro)

Tvůj případ: termostat (a jeho vlastní čidlo) je v obýváku, ale ráno 30–60
minut před budíkem chceš mít teplo v ložnici, podle ukazatele ThermoPro
tam. Řeší to nastavení `wake_sensor_entity` (v config flow integrace) +
dvě nová čísla, `wake_target_temperature` (cíl na ThermoPro, ve tvém
případě 24 °C) a `wake_boost_temperature` (na kolik se mezitím natáhne
sám termostat v obýváku, aby jistě topil i když je v obýváku už teplo —
výchozí 26 °C).

Jakmile máš nastavený *wake sensor*, chování se pro dané dny (kde běží
Garmin budík) změní takto:

1. **Před oknem předstihu** (spočítá se stejnou váhovou logikou jako
   normální preheating, jen z rozdílu `wake_target_temperature` a aktuální
   hodnoty na ThermoPro) — nic se neděje, platí normální rozvrh.
2. **V okně předstihu, dokud ThermoPro ukazuje méně než cíl** — termostat
   v obýváku se nastaví na `wake_boost_temperature`, aby topení jelo naplno,
   i kdyby obývák sám o sobě už svoji cílovku splňoval.
3. **Jakmile ThermoPro dosáhne cíle** (u tebe 24 °C) — termostat se sníží na
   `wake_target_temperature`, aby se drželo, ale dál nepřetápělo, a to až do
   budíku.
4. **Jakmile budík zazvoní** — celá tahle logika přestává platit a řízení se
   vrátí zpět k normálnímu rozvrhu (podle vlastního čidla termostatu v
   obýváku), přesně jak jsi popsal.

Pokud `wake_sensor_entity` nenastavíš, integrace se chová jako dřív: Garmin
budík jen posune čas ranního "Comfort" bloku v rozvrhu a řídí se podle
vlastního čidla termostatu.

> **Poznámka k topné soustavě:** aby tohle dávalo smysl, musí zvýšení
> setpointu na termostatu v obýváku reálně přitopit i v ložnici (typicky
> centrální kotel řízený jedním hlavním termostatem). Pokud má ložnice
> vlastní nezávislý radiátor/hlavici, potřebovala by vlastní `climate`
> entitu a vlastní zónu integrace, ne jen čidlo.

## Topná sezóna a "mírný den" (úspora energie)

Tohle jsou dvě záměrně **oddělené** vrstvy, protože řeší různě dlouhé
časové horizonty a plést je dohromady vede přesně k chybě, které jsme se
chtěli vyhnout (aby chladná srpnová noc omylem nespustila topení):

1. **Topná sezóna** (`season_start_month`/`season_end_month`, výchozí
   10 → 4) je tvrdá brána podle **kalendáře**. Mimo tyto měsíce se aktivně
   netopí vůbec — jediná výjimka je mrazová pojistka
   (`frost_protect_temperature`, výchozí 7 °C): pokud by vnitřní teplota
   klesla pod tuhle hranici i mimo sezónu (aby nezamrzly rozvody), krátce
   se zatopí na tuto bezpečnou hodnotu. Okamžitá venkovní teplota na tohle
   nemá vliv — jen měsíc v kalendáři.
2. **"Mírný den"** (`mild_outdoor_threshold`/`mild_setback`, výchozí 16 °C
   / 3 °C) běží **uvnitř** sezóny a reaguje na aktuální/předpovězenou
   venkovní teplotu za běhu: pokud je nebo bude teplo, cílová teplota se
   sníží o `mild_setback`, protože sluneční/vnitřní zisky byt pravděpodobně
   dohřejí samy. Je to schválně **odečet, ne úplné vypnutí** — predikce
   počasí není dokonalá (závisí na orientaci oken, slunci ten den), takže
   odečet šetří energii, ale nenechá tě prochladnout, když se předpověď
   netrefí. Když je zrovna zapnutý i eco mode, použije se ten silnější z
   obou odečtů, ne aby se sčítaly.

Obě věci jsou `number` entity — klidně si je za chodu doladíš (např. pokud
ti přijde 3 °C na mírný den málo/moc, nebo chceš sezónu užší/širší) bez
zásahu do kódu. Reálné chování zatím nebylo ověřeno na tvém konkrétním bytě
(tepelná setrvačnost, orientace oken) — první týdny to sleduj a hodnoty
doladi podle toho, jak moc/málo to skutečně vytápí.

## Co tohle *není*

- **Není to náhrada tado° cloudu 1:1.** Eco/rozvrh/probouzení jsou naše
  vlastní logika nad standardní `climate` entitou, ne skutečná tado° data.
- **Geofencing (podle polohy telefonu) tu není implementovaný.** Dá se ale
  snadno postavit z `switch.<zone>_away_mode` + standardní HA automatizace
  nad `person.*`/`zone.*` entitami — to už je čistě HA věc, žádné rozšíření
  navíc nepotřebuje.
- **Preheating zatím posouvá jen první "Comfort" blok dne.** Pokud máš v
  rozvrhu víc "Comfort" bloků (např. ráno i večer), předstihem se řídí jen
  ten první — u dalších se topí přesně na čas bloku.

## Co bylo a nebylo otestováno

- Logika v `decision.py` (preheating, eco setback, away override, Garmin
  přepis ranního bloku, hranice horizontu, boost/hold/revert cyklus wake
  sensoru, brána topné sezóny včetně přelomu roku, odečet za mírný den a
  že se s eco nesčítá) má jednotkové testy v `tests/` — spustíš je čistým
  `pytest tests/` bez nutnosti mít nainstalovaný Home Assistant.
- Převod mezi malovací mřížkou karty (48 slotů/den) a uloženými bloky
  (`blocksToSlots`/`slotsToBlocks`) byl ověřen ručním round-trip testem.
- **Nebylo (a nemohlo být) otestováno proti reálné instalaci Home Assistant,
  reálnému tado X přes Matter ani reálnému Garmin účtu** — tahle relace běží
  v izolovaném cloudovém kontejneru bez přístupu k tvé síti. Po instalaci
  zkontroluj hlavně: že se `climate.set_temperature`/`set_hvac_mode` volání
  chovají u tvého konkrétního Matter zařízení očekávaně, a že Garmin parsing
  (`garmin.py`) sedí na formát, který vrací tvůj účet.

## Nápady na rozšíření

- Víc "Comfort" bloků za den s vlastním předstihem pro každý.
- Přímé malování konkrétní teploty tahem (místo tří pevných režimů).
