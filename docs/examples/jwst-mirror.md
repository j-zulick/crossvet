# Example: a real Crossvet run

This report was produced by Crossvet v0.1 on 2026-11-08 and is reproduced unedited, including its Review notes.

| | |
|---|---|
| Question | How did the James Webb Space Telescope's mirror design solve the problem of launching a 6.5 m mirror, and what did its first year of science confirm? |
| Search | OpenAI built-in web search (`SEARCH_API=openai`) |
| Research and writing | `openai:gpt-4.1` (summaries: `openai:gpt-4.1-mini`) |
| Review panel | `openai:gpt-6.1-sol`, `anthropic:claude-sonnet-5-5` |
| Reviser | `openai:gpt-6.1-sol` |
| Run time | 144 s |

Both reviewers scored the first draft 4/10. The revision removed or qualified the claims they flagged, and the citation check found no cited URL that research had not read. With only two vendors configured, the reviser shares a vendor with one reviewer, so the Review notes carry a warning; adding a third vendor removes it.

---

# James Webb Space Telescope: Engineering the 6.5-Meter Mirror and First-Year Science Discoveries

## Introduction

The James Webb Space Telescope (JWST) uses a 6.5-meter primary mirror made from 18 segments. Its mirror wings and other large structures folded for launch, then unfolded during the journey toward its orbit around the Sun–Earth L2 point. Mechanical deployment was followed by months of cooling and optical alignment.

JWST’s first year of science operations, approximately July 2022–July 2023, produced important results in galaxy evolution, exoplanet atmospheres, star formation, and Solar System science. This report explains the engineering that made those observations possible and summarizes the scientific findings, distinguishing preliminary candidates from confirmed measurements. Selected later results are explicitly identified as outside the first-year announcement window.

## Engineering Solutions: JWST Mirror Design and Deployment

### The Challenge

JWST’s primary mirror was too wide to fit inside the Ariane 5 launch fairing in its observing configuration. Engineers therefore designed a segmented mirror with folding wings, allowing a large collecting surface to fit within the available launch space [1].

The challenge extended beyond unfolding the telescope. The mirror had to retain its optical shape at cryogenic temperatures, and its separate segments had to be aligned accurately enough to function as one optical system [3].

### Segmented Mirror Architecture and Folding Techniques

- **Eighteen Mirror Segments:** The primary mirror consists of 18 hexagonal segments, each approximately 1.32 meters across, forming a 6.5-meter aperture [1].
- **Folding Wings:** A central section holds 12 segments. Two side wings, each carrying three segments, folded backward for launch and rotated outward before latching into their observing positions [2].
- **Architecture Trade-offs:** Engineers evaluated configurations with more segments, including a 36-segment design. The adopted 18-segment architecture balanced aperture size with the provision of full actuator control for each segment [3].
- **Observatory-Wide Deployment:** The sequence proceeded from the sunshield and supporting structures to the secondary-mirror tripod and then the primary-mirror wings. The more than 50 major deployment steps and 178 release mechanisms applied to the observatory as a whole, not just the primary mirror [2].

### Advanced Materials and Structure

- **Beryllium Mirror Segments:** Beryllium was selected for its low mass, stiffness, and dimensional stability at cryogenic temperatures. Material was removed from the back of each segment to leave a lightweight ribbed structure. Each mirror alone weighs approximately 20 kilograms, excluding its supporting and actuation hardware [1,4].
- **Gold Coating:** A gold layer approximately 100 nanometers thick improves infrared reflectivity. A thin silicon dioxide overcoat protects the gold [1].
- **Graphite-Composite Backplane:** A thermally stable graphite-composite backplane supports the mirror segments and limits structural changes that would disturb alignment [5].

### Deployment and Alignment Mechanisms

Mechanical unfolding, release from launch restraints, and optical alignment were distinct stages.

- **Wing Deployment:** Following sunshield deployment and unfolding of the secondary-mirror support structure, the two primary-mirror wings swung outward and latched into place during the second week after launch [2,6].
- **Segment Extraction:** In January 2022, engineers commanded 126 primary-mirror actuators and six secondary-mirror actuators to move the mirrors out of their launch configurations. Primary segments moved approximately 12.5 millimeters to clear their launch restraints. More than a million motor revolutions were accumulated across the deployment operation—not by each segment individually [7].
- **Seven Actuators per Primary Segment:** Six actuators control each segment’s rigid-body position and orientation; a seventh adjusts its radius of curvature. Together, these permit the position and shape corrections needed for optical phasing [3].
- **Wavefront Sensing and Control:** Engineers used NIRCam images, including defocused star images, to calculate alignment corrections. Iterative coarse and fine adjustments over several months brought the separate segments into alignment as one effective mirror [1,14].
- **Ongoing Optical Monitoring:** Alignment remains an operational task rather than a one-time “final” setting. A November 2024 monitoring account reported residual wavefront error of about 65 nanometers, compared with a 150-nanometer design target. That later performance figure should not be treated as a dated measurement of the initial commissioning endpoint [8].

### Integrated Systems Reliability

- **Ground Testing:** Deployment testing and simulations addressed an observatory with more than 300 potential single-point failures. A one-sixth-scale optical testbed separately helped validate wavefront-sensing and alignment techniques [2,14].
- **Thermal Compensation:** Components manufactured and measured at room temperature change shape as they cool. Engineers deliberately incorporated compensating offsets so that thermal contraction would bring the optics toward their required cold shapes [6].
- **Deployment During Transit:** Major unfolding took approximately two weeks and was controlled remotely from Earth while JWST traveled toward L2. Cooling and optical commissioning continued afterward; arrival near L2 did not mark the beginning of mechanical deployment [2].

## Major Scientific Findings: JWST’s First Year (July 2022–July 2023)

NASA released JWST’s first suite of full-color images and spectra on July 12, 2022, following the unveiling of its first deep-field image the previous day. Targets included the SMACS J0723 galaxy-cluster field, Stephan’s Quintet, and the exoplanet WASP-96b [21].

The findings below emphasize results announced by approximately July 2023. Later announcements are labeled separately.

### Observations of the Early Universe and Galaxy Evolution

- **Early Galaxy Candidates:** Initial imaging revealed unusually luminous galaxy candidates at estimated redshifts around z ≈ 10–12. These observations opened a new window onto early galaxy formation, but an estimated redshift from imaging is not equivalent to spectroscopic confirmation [10].
- **Candidate Surveys:** Early surveys reported substantial samples of potentially very distant galaxies. Their interpretation required follow-up because lower-redshift objects can sometimes resemble high-redshift galaxies in broadband images [12].
- **Galaxy Chemistry and Evolution:** Deep observing programs such as JADES expanded the study of early galaxies and their chemical signatures. Such measurements help investigate how gas and chemical enrichment influenced galaxy evolution [9,13].
- **Limits on Interpretation:** An unexpectedly bright early galaxy does not, by itself, establish that the system is mature or exceptionally massive. Conclusions about its stellar population and mass depend on how its light is interpreted.
- **Later Spectroscopic Follow-up:** A paper published after the July 2023 cutoff confirmed two luminous galaxies at z > 11, but identified another candidate previously estimated at z ≈ 16 as a foreground galaxy at z = 4.9. This illustrates why the most extreme imaging-based distance claims must remain provisional until checked spectroscopically [11].

### Exoplanet Atmospheres and Habitability

- **Carbon Dioxide in WASP-39b:** JWST made the first unambiguous detection of carbon dioxide in an exoplanet atmosphere, observing the gas giant WASP-39b. The result demonstrated its ability to distinguish molecular absorption features in exoplanet spectra [15].
- **Rocky-Planet Measurements:** First-year observations included temperature measurements of rocky planets and constraints on their atmospheres, including a result ruling out a thick carbon-dioxide atmosphere in one case. Probing an Earth-sized planet does not necessarily mean detecting an atmosphere around it [16,17].
- **Clouds and Atmospheric Chemistry:** Observations revealed complex cloud behavior and atmospheric constituents including potassium and sulfur dioxide. These measurements broadened the chemical and physical information obtainable from exoplanet spectra [16].
- **Later Result—K2-18b:** The methane and carbon-dioxide findings for K2-18b were announced in September 2023, outside the first-year window. A hydrogen-rich atmosphere above a possible ocean is one interpretation of those measurements; an ocean, habitability, or a biological origin for the molecules was not established [16].

### Star and Planet Formation, Solar System Science

- **Stellar Birthplaces:** The July 12, 2023 anniversary image of Rho Ophiuchi showed protostellar jets and dusty regions associated with the formation of Sun-like stars [20].
- **Dust in Star-Forming Regions:** Mid-infrared observations of the Pillars of Creation highlighted dust structures that are important to understanding star formation [17].
- **Main-Belt Comet Water:** JWST confirmed water vapor in a main-belt comet for the first time, providing evidence relevant to the distribution and survival of water in the Solar System [16].
- **Enceladus’ Plume:** Observations mapped a large water plume from Saturn’s moon Enceladus, extending the telescope’s scientific reach to active processes on nearby icy worlds [16].
- **Other 2023 Findings:** Calendar-year summaries also include water vapor in a rocky planet-forming region and a carbon source on Europa’s surface. These should not automatically be counted as first-year announcements: the Europa result appeared after the July cutoff. Disk-water observations inform models of planet formation and water availability, but do not demonstrate the habitability of future planets [16,18].

### Stellar Evolution and Heavy Element Formation

The following highlighted results belong to later 2023 announcements rather than the July 2022–July 2023 first-year window:

- **Heavy Elements:** JWST detected tellurium associated with a stellar merger, providing evidence relevant to the production of heavy elements [19].
- **Supernova and Nebular Imaging:** Later releases of SN 1987A and the Crab Nebula revealed detailed structures in stellar remnants. These observations supplied additional material for studying stellar evolution and its aftermath [18].

### Operational Achievements

- **Science Efficiency:** By its first operational anniversary, JWST was using approximately 80% of its time on prime science programs. This is a reported utilization figure, not a claim that science occupied more than 80% of every period after commissioning [20].
- **Calibration and Data Quality:** Work by STScI and the scientific community continued to improve calibration and the interpretation of observations. Reliable scientific conclusions depend on this continuing work as well as on the telescope’s optical performance [20].

## Conclusion

JWST’s 6.5-meter mirror became practical through a combination of segmentation, folding wings, lightweight beryllium construction, infrared-reflective gold coatings, a stable backplane, and precision actuators. Mechanical deployment during transit to L2 established the telescope’s configuration; subsequent cooling and image-based alignment made its segments function together optically.

During its first year of science operations, JWST delivered deep views of early galaxy candidates, detailed exoplanet spectra, observations of stellar birthplaces, and measurements of water in the Solar System. The strongest interpretation of these achievements distinguishes candidates from spectroscopic confirmations, atmospheric measurements from habitability claims, and first-year announcements from later discoveries.

## Sources

1. [Webb’s Mirrors – NASA Science](https://science.nasa.gov/mission/webb/webbs-mirrors/)
2. [Deployment – NASA Science](https://science.nasa.gov/mission/webb/deployment/)
3. [The James Webb Space Telescope Mission: Optical Telescope Element Design, Development, and Performance – NASA Technical Report](https://ntrs.nasa.gov/api/citations/20230010809/downloads/9_McElwain_2023_PASP_135_058001.pdf)
4. [Progress in the Fabrication and Testing of Telescope Mirrors for JWST – NASA Technical Report](https://ntrs.nasa.gov/search.jsp?R=20120007852)
5. [JWST Telescope – JWST User Documentation](https://jwst-docs.stsci.edu/jwst-observatory-hardware/jwst-telescope)
6. [Webb Telescope Launch Media Kit – NASA](https://science.nasa.gov/wp-content/uploads/2024/08/webbmediakit.pdf)
7. [Webb Mirror Segment Deployments Complete – NASA Science](https://science.nasa.gov/blogs/webb/2022/01/19/webb-mirror-segment-deployments-complete/)
8. [Monitoring Webb’s Mirrors for Optimal Optics – NASA Science](https://science.nasa.gov/blogs/webb/2024/11/08/monitoring-webbs-mirrors-for-optimal-optics/)
9. [Galaxies Over Time – NASA Science](https://science.nasa.gov/mission/webb/galaxies-over-time/)
10. [Two Remarkably Luminous Galaxy Candidates at z ≈ 10–12 Revealed by JWST – arXiv](https://arxiv.org/abs/2207.09434)
11. [Confirmation and refutation of very luminous galaxies in the early Universe – Nature](https://www.nature.com/articles/s41586-023-06521-7)
12. [NASA Recaps Webb Telescope Findings From AAS Meeting – NASA](https://www.nasa.gov/universe/nasa-recaps-webb-telescope-findings-from-aas-meeting/)
13. [Galaxies Over Time – NASA Science](https://science.nasa.gov/mission/webb/galaxies-over-time/)
14. [Wavefront Sensing and Control – NASA Science](https://science.nasa.gov/mission/webb/wavefront-sensing-and-control/)
15. [Webb telescope spots CO2 on exoplanet for first time: what it means for finding alien life – Nature News](https://www.nature.com/articles/d41586-022-02350-2)
16. [News | Webb | Missions | Astrobiology – NASA](https://astrobiology.nasa.gov/missions/jwst/news/)
17. [NASA Science Live: Webb’s First Year | News | Astrobiology – NASA](https://astrobiology.nasa.gov/news/nasa-science-live-webbs-first-year/)
18. [Webb: 2023 Year in Headlines – NASA Science](https://science.nasa.gov/asset/webb/webb-2023-year-in-headlines/)
19. [2023 ESA/Hubble and ESA/Webb highlights | ESA/Hubble](https://esahubble.org/forscientists/announcements/sci23005/)
20. [One for the Record Books | STScI](https://www.stsci.edu/contents/annual-reports/2023/one-for-the-record-books)
21. [Webb Mission Timeline – NASA Science](https://science.nasa.gov/mission/webb/webb-mission-timeline/)

---

## Review notes

- Reviewed by 2 models from 2 vendor(s) (openai:gpt-6.1-sol, anthropic:claude-sonnet-5-5); critiques were anonymized before voting.
- Draft scores: anthropic:claude-sonnet-5-5 4/10, openai:gpt-6.1-sol 4/10
- Most useful critique (peer vote): openai:gpt-6.1-sol
- Warning: the reviser (openai:gpt-6.1-sol) shares a vendor with reviewer(s) openai:gpt-6.1-sol; set REVIEW_REVISER_MODEL to a model from another vendor for a fully independent revision.
