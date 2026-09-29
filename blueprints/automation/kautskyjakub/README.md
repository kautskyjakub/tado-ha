# Ranní probuzení – simulace úsvitu

Blueprint `usvit_simulace.yaml` postupně rozsvítí ložnici podle budíku z Garmin hodinek
(`sensor.obyvak_next_garmin_wake`). Tato verze v repozitáři je **okomentovaná**; HA si při
uložení přes API blueprint přeformátuje a komentáře zahodí.

## Instance v HA

| Co | Entita |
|---|---|
| Automatizace | `automation.loznice_ranni_probuzeni_simulace_usvitu` |
| Hlavní vypínač | `input_boolean.probuzeni_aktivni` |
| I o víkendu | `input_boolean.probuzeni_i_o_vikendu` |
| Úsvit běží (jen pro logiku) | `input_boolean.probuzeni_bezi` |
| Délka rampy R | `input_number.probuzeni_delka_rampy` (výchozí 35 min) |
| Poměr lux polštář/senzor | `input_number.probuzeni_pomer_lux` |
| Uložený stav AL | `input_text.probuzeni_ulozeny_stav` (`1,1,1` = hlavní, adapt_brightness, adapt_color) |
| Start úsvitu | `sensor.probuzeni_start_usvitu` (template helper = budík − R) |
| Zrychlený test | `script.probuzeni_otestovat_usvit` (pole `delka_min`, výchozí 3) |

## Průběh (R = 35 min, T = budík)

| Fáze | Čas | Lampy | Strop u okna | Strop v hloubce | Teplota |
|---|---|---|---|---|---|
| 0 Rozbřesk | T−35 → T−25 | 1 → 30 % | – | – | 2202 K |
| 1 Svítání | T−25 → T−18 | 30 → 50 % | 1 žárovka 1 → 20 % | – | 2202 K |
| 2 Rozednění | T−18 → T−10 | 50 → 70 % | skupina → 30 % | 1 žárovka 1 → 15 % | 2202 → 2700 K |
| 3 Východ | T−10 → T0 | 70 → 100 % | 30 → 85 % | skupina → 50 % | 2700 → 4000 K |
| 4 Den | T0 → T+15 | 100 % | 85 → 100 % | 50 → 100 % | 4000 → 5500 K |
| 5 Držení | T+15 → T+20 | 100 % | 100 % | 100 % | 5500 K |
| 6 Konec | T+20 | `adaptive_lighting.apply` s `transition: 60`, pak obnova přepínačů AL | | | |

- **Jas** se interpoluje logaritmicky: $b(t) = b_1 \cdot (b_2 / b_1)^{f}$, kde $f$ je podíl uplynulého
  času v dané fázi. *Zjednodušeně:* každý krok jas vynásobí stejným koeficientem, takže oko vnímá
  rovnoměrný nárůst.
- **Teplota barvy** se interpoluje lineárně v miredech ($\text{mired} = 10^6 / K$). *Zjednodušeně:*
  v teplé oblasti se mění pomaleji, ve studené rychleji – tak, jak to vnímáme.
- Smyčka má krok 30 s a každý příkaz má `transition` 30 s; žárovky se ovládají **jednotlivě**
  (skupiny se jen rozbalí přes atribut `entity_id`).

## Kdy se úsvit nespustí

- `input_boolean.probuzeni_aktivni` je vypnutý, osoba není doma, víkend bez „i o víkendu“, nebo už něco svítí.
- V místnosti je víc než 50 lx (při nedostupném senzoru: slunce nad 5° a roleta není zatažená).
- **Slunce vyjde víc než 15 min před budíkem** (vstup *Rezerva východu slunce před budíkem*) – denní
  světlo by simulaci stejně přebilo. Typicky konec září / začátek října a jaro.

## Přerušení

- Dlouhý stisk `event.shelly_loznice_vstup_0` (horní tlačítko rolet): při zapnutém spánkovém režimu
  ho vypne (původní automatizace), při běžícím úsvitu úsvit ukončí a **zhasne lampy i strop**
  (vstup *Chování po přerušení tlačítkem* = Vypnout světla). Do 2 h po skončení úsvitu dlouhý stisk
  také zhasne lampy a strop (větev v `automation.spankovy_rezim_vypnuti_long_push_nahoru`).
  Úsvit na začátku vypíná `switch.sleep_mode`, takže se stavy nepotkají.
- Změna vstupů nástěnných vypínačů (`binary_sensor.shelly2pmg3_28372f26a0e4_vstup_0/1`).
- Ruční změna světel (vypnutí, zapnutí zvenku, změna jasu nebo barvy mimo toleranci).
- Vypnutí `input_boolean.probuzeni_bezi` nebo `input_boolean.probuzeni_aktivni`.

Po přerušení: výchozí **ponechat světla a předat AL**; volitelně vypnout, nebo plný jas.

## Kalibrace luxů

1. Spusť test (dashboard Ložnice → *Otestovat úsvit*), nebo počkej na ostrý běh.
2. V T0 (nebo na konci testu při plném jasu) změř mobilem lux na polštáři a současně odečti
   hodnotu `sensor.myggspray_wrlss_mtn_sensor_osvetleni_2`.
3. Poměr polštář / senzor zapiš do `input_number.probuzeni_pomer_lux`.
4. Pokud chceš dorovnávání, zapni v automatizaci *Korekce podle senzoru*. Uprav případně procenta
   v sekci *Průběh (kalibrace)* tak, aby v T0 bylo na polštáři ~250–300 lx.
