"""Task 4: output/report/RAPOR.md (Turkish) generated from the JSON results of the other steps."""
import json
import os

import common as C


def load(n):
    with open(C.rp('output', 'report', n), encoding='utf-8') as f:
        return json.load(f)


def ok(b):
    return 'GEÇTİ' if b else 'KALDI'


def main():
    m = load('case_metrics.json')
    v = load('case_v2_validation.json')
    s = load('stand_params.json')
    b, val, pc = v['build'], v['validation'], v['print_check']
    top = val['topology']
    cav = m['cavity']
    sec = {r['z']: r for r in cav['sections'] if 'width_x' in r}
    L = []
    w = L.append
    w('# Panter çakmak kılıfı v2 + sergi standı — geometri raporu\n')
    w('Tüm ölçüler mm. Kaynak: `lighter-Panter-YENI-YAKI-A1.3mf` (değiştirilmedi). Üreten: `pipeline/geometry/` '
      '(komutlar `pipeline/geometry/README.md`). Ayrıntılı sayılar: `case_metrics.json`, `case_v2_validation.json`, '
      '`stand_params.json`, `stand_layout.json`.\n')

    w('## 1. Kaynak modelin ölçümleri\n')
    w(f"- {m['counts']['vertices']:,} köşe, {m['counts']['triangles']:,} üçgen; tek nesne, tek kabuk (shell). "
      f"Kenarların tamamı 2 üçgenle paylaşılıyor (açık kenar 0, manifold dışı kenar 0), yönler tutarlı, "
      f"hacim +{m['topology']['signed_volume_mm3']:.0f} mm³, cins (genus) {m['topology']['genus']}. "
      f"Kendi kendini kesen üçgen çifti: {m['topology']['self_intersections']['intersecting_triangle_pairs']} (Blender BVH).")
    cols = ', '.join(f"{k} {c['triangles']:,}" for k, c in m['colours'].items())
    w(f"- Renkler üçgen bazında (`pid=2 p1=…`), Bambu `paint_color` ile birebir aynı: {cols}.")
    bb = m['bbox']
    w(f"- Sınır kutusu: X {bb['min'][0]:.2f}…{bb['max'][0]:.2f}, Y {bb['min'][1]:.2f}…{bb['max'][1]:.2f}, "
      f"Z {bb['min'][2]:.2f}…{bb['max'][2]:.2f} (boyut {bb['size'][0]:.1f} × {bb['size'][1]:.1f} × {bb['size'][2]:.1f}). Yukarı ekseni +Z.")
    w("- Ön yüz: **−Y** (\"YENİ YAKI\" etiketi −Y'ye bakıyor, −Y'den bakınca düz okunuyor). Kafa +X tarafında, ayaklar −X/−Y'de.")
    r25 = sec[25]
    w(f"- Çakmak yuvası: oval, uzun ekseni X boyunca, eksen XY = ({cav['axis_xy'][0]:.3f}, {cav['axis_xy'][1]:.3f}) "
      f"(z 1…45 arasında sapma {cav['axis_spread_mm']} mm). İç ölçü z = 0.3 … 49.8 boyunca sabit "
      f"**{r25['width_x']:.3f} × {r25['depth_y']:.3f}** → 24 × 12 tabana göre yan başına "
      f"{r25['clearance_per_side_x']:.3f} / {r25['clearance_per_side_y']:.3f} boşluk (notlardaki 0,30 ile uyumlu). "
      f"En altta (z ≈ 0) yuva ağzı hafif pahlı: {sec[0.0025]['width_x']:.2f} × {sec[0.0025]['depth_y']:.2f}.")
    w(f"- Yuvanın **altı açık, taban yok** (kaynakta çakmak doğrudan masaya basardı, oturma z = 0). "
      f"Duvar üst kotu: ön/arka/sol {cav['wall_top_z_by_side']['on_-Y']:.2f} (0,05 adımla ölçüldü; ≈ 50,0), "
      f"sağ (+X, figür gövdesi) {cav['wall_top_z_by_side']['sag_+X']:.2f}.")
    u = m['underside']
    w(f"- Alt yüz: **kaynak zaten düz.** z = 0'da {u['vertices_at_z0']:,} köşe ve {u['faces_on_z0_area_mm2']:.0f} mm² düz yüzey var "
      f"(z = 0,0025'teki kesitin %{100 * u['flat_contact_fraction']:.0f}'i). Ayaklar dahil hiçbir şey z = 0'ın altına sarkmıyor. "
      f"Tek sapma, örgü dokusunun alt kenarındaki 0,3–0,6 mm genişliğindeki yuvarlatılmış/dişli kenar. "
      f"(Önceki notta geçen \"en alt köşeler z 0,007…0,3\" ifadesi yalnızca bu kenar bandı için doğru.)")
    w('- Diyagnostik görseller: `kaynak_*.png` (4 yan + alt + izometrik), `kaynak_alan_z.png`, `kaynak_alt_kesitler.png`, '
      '`kaynak_alt_yukseklik.png`, `kaynak_kavite_kesitler.png`, `kaynak_duvar_ust.png`.\n')

    w('## 2. Kesme düzlemi (z_cut) kararı\n')
    zc = b['z_cut']
    w(f"- Kesit alanı A(z) z = 0'da {u['section_area_at_z0p0025_mm2']:.0f} mm²'den başlayıp ilk ~0,1 mm'de çok hızlı artıyor "
      f"(dA/dz ≈ 300 mm²/mm: alt kenar yuvarlaması). Sonra gövdenin doğal genişleme hızına iniyor (0–45 mm²/mm, doku dalgalanması). "
      f"Eşik 60 mm²/mm ile kırılma noktası **{zc['knee']:.3f}**. Bir katmana (0,12) yukarı yuvarlandı: **z_cut = {zc['value']:.2f}**.")
    rm = b['removed']
    w(f"- Kaldırılan: z < {zc['value']:.2f} dilimi, en fazla derinlik {rm['max_depth_mm']:.2f}, hacim {rm['volume_mm3']:.1f} mm³. "
      f"Bu dilimin plinth prizmasının dışında kalan kısmı {rm['source_below_cut_outside_plinth_mm3']} mm³. "
      f"Yan etkisi: kılıf duvarının üstü artık oturma düzleminden {val['cavity']['wall_top_above_seat']:.2f} yukarıda "
      f"(50,00 yerine; fark bir katman).\n")

    w('## 3. v2 değişiklikleri\n')
    pl, ho = b['plinth'], b['hole']
    w(f"- **Kaide (plinth):** z_cut kesitinin dış konturu, delikleri dolu (yuva tabanını da oluşturuyor), "
      f"{pl['outset_mm']} mm dışa ofset, 3 µm sadeleştirme. Alanı {pl['footprint_area_mm2']:.1f} mm², "
      f"{pl['footprint_vertices']} köşe. {pl['height']:.1f} mm düz aşağı ekstrüzyon. "
      f"Yan duvar rengi komşu kaynak üçgeninden alındı ({b['colours']['plinth_side_colours']}); alt yüz, yuva tabanı ve delik Pembe.")
    w(f"- **Pim deliği:** yuva ekseninde ({ho['axis_xy'][0]:.3f}, {ho['axis_xy'][1]:.3f}). Model Ø {ho['model_diameter']} "
      f"({ho['polygon_segments']} kenarlı çokgen; iç teğet çapı tam {ho['model_diameter']}). Alt ağızda {ho['bottom_chamfer']} × 45° pah. "
      f"Taban kalınlığı {ho['total_floor_under_lighter']:.1f} ≤ 4 olduğu için **delik boydan boya** ({ho['depth']:.1f}), yuvaya açılıyor. "
      f"Çakmak deliğin çevresindeki düz halkaya oturur; yuvaya giren geometri yok.")
    w(f"- **Yöntem:** (kaynak ∪ kaide prizması) − delik, manifold3d float64. Kaynağın z_cut üstündeki "
      f"{val['design_preservation']['source_triangles_fully_above_cut']:,} üçgeninin {val['design_preservation']['unchanged_in_v2']:,} "
      f"tanesi bit-düzeyinde aynı (yalnızca z +{b['boolean']['z_shift_applied']:.2f} öteleme). Eksik 2 üçgen kaynaktaki sıfır-alanlı "
      f"dejenere üçgenler. Kaynak tek kabuk olduğu için ayrı kabuk birleştirme gerekmedi; sonuç tek, kapalı katı.\n")

    w('## 4. Doğrulama (v2)\n')
    fp, hs = val['footprint'], val['hole']
    h15 = [r for r in hs['sections'] if r.get('z') == 1.5][0]
    h0 = hs['sections'][0]
    rows = [
        ('Kapalı (açık kenar 0) / manifold (≥3 yüzlü kenar 0)', f"{top['boundary_edges']} / {top['nonmanifold_edges']}", top['boundary_edges'] == 0 and top['nonmanifold_edges'] == 0),
        ('Yön tutarlılığı (tekrarlı yönlü kenar)', f"{top['directed_duplicate_edges']}", top['directed_duplicate_edges'] == 0),
        ('Kabuk sayısı / manifold3d durumu', f"{top['shells']} / {top['manifold3d_status']}", top['shells'] == 1),
        ('Hacim işareti', f"+{top['signed_volume_mm3']:.1f} mm³ (kaynak {top['source_volume_mm3']:.1f})", top['signed_volume_mm3'] > 0),
        ('Kendi kendini kesme (Blender BVH)', f"{val.get('self_intersections')} çift", val.get('self_intersections') == 0),
        ('min z', f"{fp['min_z']}", fp['min_z'] == 0.0),
        ('Taban düzlüğü: 0 < z < 0,05 köşe', f"{fp['vertices_between_0_and_0p05']}", fp['vertices_between_0_and_0p05'] == 0),
        ('Taban alanı z = 0 / beklenen', f"{fp['bottom_face_area_mm2']:.2f} / {fp['expected_area_footprint_minus_chamfer_mouth']:.2f}", abs(fp['bottom_face_area_mm2'] - fp['expected_area_footprint_minus_chamfer_mouth']) < 0.1),
        ('Sınır kutusu', f"{val['bbox']['size'][0]:.2f} × {val['bbox']['size'][1]:.2f} × {val['bbox']['size'][2]:.2f}", True),
        ('Delik çapı (z = 1,5; iç teğet)', f"{h15['inscribed_d']:.3f}, merkez {h15['centre']}", abs(h15['inscribed_d'] - 3.3) < 0.01),
        ('Delik ağzı (z ≈ 0)', f"Ø {h0['inscribed_d']:.2f} (3,3 + 2 × 0,4 pah)", abs(h0['inscribed_d'] - 4.1) < 0.02),
        ('Delik yuvaya açılıyor (z = 3,01)', f"{hs['opens_into_cavity']}", hs['opens_into_cavity']),
        ('Yuva kesitleri önce/sonra (8 kot, simetrik fark)', f"maks {val['cavity']['max_sym_diff_mm2']} mm²", val['cavity']['max_sym_diff_mm2'] < 1e-6),
        ('Oturma düzleminin üstünde yuvada malzeme', f"{'yok' if val['cavity']['nothing_inside_cavity_above_floor'] else 'VAR'}", val['cavity']['nothing_inside_cavity_above_floor']),
        ('Renkler korunuyor (kaynak üçgenleri)', f"{val['design_preservation']['source_colour_preserved_on_all_source_triangles']}", val['design_preservation']['source_colour_preserved_on_all_source_triangles']),
        ('3MF yeniden okuma (p1 = paint_color, köşe yuvarlama)', f"{v['roundtrip_3mf']['p1_equals_built']}, {v['roundtrip_3mf']['max_vertex_roundoff']:.1e}", v['roundtrip_3mf']['p1_equals_built'] and v['roundtrip_3mf']['paint_matches_p1']),
    ]
    w('| Kontrol | Sonuç | Durum |\n|---|---|---|')
    for a_, b_, c_ in rows:
        w(f'| {a_} | {b_} | {ok(c_)} |')
    w('\nGörseller: `v2_alt.png`, `v2_alt_izo.png`, `v2_arka_alt_izo.png`, `v2_on_-Y.png`, `v2_izo.png`, `v2_dikey_kesitler.png`.\n')

    w('## 5. Baskı kontrolü — kılıf (Bambu A1, 0,4 nozul, 0,12 katman)\n')
    ov = pc['overhang_gt45_area_mm2_by_z']
    w(f"- Kaide aşağıda olacak şekilde basılır. Boyut tablaya sığıyor ({ok(pc['fits_A1_256'])}).")
    junc = pc['case_outline_vs_plinth']
    w(f"- Kaide/kılıf birleşimi: kılıf konturu kaidenin üstünde dışa doğru genişliyor: "
      f"+0,12'de {junc[0]['max_outward_offset_mm']:.2f}, +0,5'te {junc[2]['max_outward_offset_mm']:.2f}, +2,0'da {junc[4]['max_outward_offset_mm']:.2f} "
      f"(kaynakta tablanın hemen üstündeki genişlemeyle aynı; < 45°, desteksiz basılır).")
    st = pc.get('steep_overhang_regions_v2', [])
    ss = pc.get('steep_overhang_regions_source_shifted', [])
    big = ', '.join(f"{r_['area_mm2']} mm² z {r_['z_range'][0]}–{r_['z_range'][1]} @({r_['xy_centre'][0]},{r_['xy_centre'][1]})" for r_ in st[:5])
    import numpy as np
    d2 = np.load(C.rp('work', 'cache', 'case_v2.npz'))
    s0 = np.load(C.rp('work', 'cache', 'source.npz'), allow_pickle=True)

    def steep(Vx, Fx, z0, z1):
        t_ = Vx[Fx]
        n_ = np.cross(t_[:, 1] - t_[:, 0], t_[:, 2] - t_[:, 0])
        a_ = np.linalg.norm(n_, axis=1) / 2
        nz_ = n_[:, 2] / (2 * a_ + 1e-30)
        cz_ = t_[:, :, 2].mean(1)
        return float(a_[(nz_ < -0.5) & (cz_ > z0) & (cz_ < z1)].sum())
    zc_ = b['z_cut']['value']
    near_v2 = steep(d2['V'], d2['F'], 3.0, 3.6)
    near_src = steep(s0['V'], s0['F'], zc_, zc_ + 0.6)
    w(f"- > 60° sarkma (Bambu varsayılan destek eşiği 30°'ye karşılık gelir) kümeleri: {big}. Toplam {sum(r_['area_mm2'] for r_ in st):.0f} mm². "
      f"Kaynakta aynı ölçüm {sum(r_['area_mm2'] for r_ in ss):.0f} mm² (fark, kaldırılan yuvarlak alt kenar). Kafa, kollar, kulak ve ayak altları kaynakla aynı. "
      f"Kaynak proje **ağaç destek, yalnız tabladan** ayarlıydı; v2'de de aynı ayar önerilir.")
    w(f"- Kaide üstündeki ilk 0,6 mm'de > 60° sarkan alan {near_v2:.1f} mm² (kaynakta aynı bant: {near_src:.1f} mm²). "
      f"Bu, kılıfın kaide kenarından en fazla ~0,3 mm/katman dışa taşması. Kaynakta bu çıkıntı tablanın 0,12 mm üstündeydi, şimdi 3 mm üstünde. "
      f"Dolayısıyla \"yalnız tabladan\" ağaç destek kaide çevresine küçük destek koyabilir. Önizlemede görülürse kaide çevresine destek engelleyici "
      f"(support blocker) konulmalı. Alternatif: `--z-cut 0.6` (genişleme bitmiş olur, duvar 0,48 mm daha kısalır). **Dilimleyicide kontrol edilmedi.**")
    wt = pc['wall_thickness_mm']
    sw = min(r_['min_radial_wall'] for r_ in pc['sleeve_min_radial_wall'])
    w(f"- Duvar kalınlığı: kılıf duvarı (yuva → dış) en ince **{sw:.2f}** (yan kısımlarda; 3 çevre çizgisi sığar). "
      f"Yüzey ışın örneklemesi: medyan {wt['p50']:.2f}, %5'lik dilim {wt['p05']:.2f}. Örneklerin %{100 * wt['frac_below_0p4']:.0f}'i 0,4'ün altında; "
      f"bunlar örgü pullarının ince kenarları. Kaynaktaki bu doku ayrıntısı 0,4 nozulda kısmen kaybolur (tasarım gereği, değiştirilmedi).\n")

    w('## 6. Sergi standı\n')
    t = s['tiers']
    cs = s['case']
    w(f"- Ölçülen kılıf (pim deliğine göre): taban izi X {cs['footprint_bounds_rel_hole'][0]:.1f}…{cs['footprint_bounds_rel_hole'][2]:.1f}, "
      f"Y {cs['footprint_bounds_rel_hole'][1]:.1f}…{cs['footprint_bounds_rel_hole'][3]:.1f}; üstten siluet X {cs['silhouette_bounds_rel_hole'][0]:.1f}…"
      f"{cs['silhouette_bounds_rel_hole'][2]:.1f}, Y {cs['silhouette_bounds_rel_hole'][1]:.1f}…{cs['silhouette_bounds_rel_hole'][3]:.1f}; yükseklik {cs['height']:.2f}.")
    w('| Kat | Pim | Halka R | Plaka Ø | Plaka üstü z | Komşu boşluk | Kolona boşluk | Üst plakaya düşey boşluk (kılıf / çakmak) | Çakmak yerinde takılır mı |')
    w('|---|---|---|---|---|---|---|---|---|')
    for k in t:
        vc = k.get('vertical_clearance_case_top_to_plate_above')
        vl = k.get('vertical_clearance_lighter_top_to_plate_above')
        w(f"| {k['name']} | {k['pins']} | {k['ring_radius']:.1f} | {k['plate_diameter']:.0f} | {k['z_plate_top']:.0f} | "
          f"{k['neighbour_gap_min']:.1f} | {k['column_gap_min']:.1f}"
          + (f" (tabela/tutucuya {k['obstacle_gap_min']:.1f})" if k.get('obstacle_gap_min') is not None else '')
          + f" | {'—' if vc is None else f'{vc:.1f} / {vl:.1f}'} | "
          + ('—' if 'lighter_insertable_in_place' not in k else ('evet' if k['lighter_insertable_in_place'] else 'hayır, kılıf pimden alınır')) + ' |')
    j = s['joints']
    sg = s['sign']
    w(f"\n- Plaka kalınlığı {s['params']['plate_thickness']}, plaka üst yüzeyleri {s['params']['tier_pitch']:.0f} aralıkla. "
      f"Kolon Ø {s['params']['column_diameter']:.0f}, 2 segment + üst parça. "
      f"Bağlantı: altıgen pim/soket (pim AA {j['spigot_af']}, soket ve plaka deliği AA {j['socket_and_plate_hole_af']}, yan başına {j['clearance_per_side']}). "
      f"Pim boyu {j['spigot_length_above_shoulder']}, soket derinliği {j['socket_depth']}, soket tavanı altıgen piramit (desteksiz). Dönmeye karşı kilitli. "
      f"Plaka, alt segmentin omzu ile üst segmentin alt yüzü arasında sıkışır. Her plakanın ön (−Y) kenarında hizalama çentiği var.")
    w(f"- Pimler Ø {s['params']['pin_diameter']}, yükseklik {s['params']['pin_height']}, üst pah {s['params']['pin_top_chamfer']}. "
      f"Kılıf deliğinde radyal boşluk {s['pin_in_hole']['radial_play']}; pim ucu çakmak tabanının {s['pin_in_hole']['pin_top_below_lighter_seat']:.1f} altında kalır.")
    w(f"- Tabela: {s['params']['sign_width']:.0f} × {s['params']['sign_height']:.0f} × {s['params']['sign_thickness']:.0f} boş panel. "
      f"Dikeyden {sg['tilt_deg']:.0f}° geriye yatık (yüzü öne/yukarı bakar). Merkezi üst plakanın {s['params']['sign_gap_above_top_plate']:.0f} üstünde. "
      f"Üst parçadaki eğik yuvaya (genişlik {sg['slot_width']:.1f}, derinlik {sg['slot_depth']:.0f}) takılır; panel düz basılır. "
      f"Standın toplam yüksekliği {s['overall']['height']:.1f}.")
    w(f"- Çakışma kontrolleri: stand parçaları arası hacim kesişimi {s['stand_part_overlaps_mm3'] or 'yok'}. "
      f"Kılıf ↔ stand kesişimi maks {s['case_vs_stand']['max_intersection_mm3']} mm³ (kılıf plakaya yalnızca temas eder). "
      f"Kılıf ↔ kılıf en küçük boşluk {s['case_vs_case']['min_gap_mm']} (kılıf vekili 0,05 mm sadeleştirilmiş).")
    w('\n**Montaj sırası:**\n')
    for x in s['overall']['assembly_order']:
        w(f'{x}  ')
    w('\n**Parça listesi ve baskı yönü** (hepsi desteksiz, min z = 0):\n')
    w('| Parça | Boyut | Hacim mm³ | Kapalı/manifold | Maks. sarkma (dikeyden) | Baskı yönü |')
    w('|---|---|---|---|---|---|')
    orient = {'plaka': 'düz, pimler yukarı', 'kolon': 'dik, soket tablada (kenar çıkıntısı/brim önerilir)',
              'ust_parca': 'dik, soket tablada (brim önerilir)', 'tabela': 'düz yatık'}
    for c in s['parts']:
        o = next(v_ for k_, v_ in orient.items() if c['name'].startswith(k_))
        w(f"| {c['name']} | {c['bbox_size'][0]:.0f} × {c['bbox_size'][1]:.0f} × {c['bbox_size'][2]:.1f} | {c['volume_mm3']:.0f} | "
          f"{ok(c['watertight'] and c['oriented'] and c['shells'] == 1)} | {c['max_overhang_deg_from_vertical']:.0f}° | {o} |")
    w(f"\n3MF tabla yerleşimi (`stand_tumu.3mf`, {len(s['plates_3mf'])} tabla, 256 × 256): "
      + '; '.join(f"Tabla {i + 1}: " + ', '.join(q['part'] for q in pl) for i, pl in enumerate(s['plates_3mf'])) + '.')
    w('Görseller: `stand_dolu_*.png` (14 kılıf takılı), `stand_bos_*.png`.\n')

    w('## 7. Açık riskler / doğrulanmayanlar\n')
    w('- 0,30 mm/yan çakmak geçme payı yalnızca geometrik olarak ölçüldü; fiziksel uyum ilk baskıda denenmeli.')
    w('- 3,3 mm delik / 3,0 mm pim (yan başına 0,15) FDM\'de sıkı ya da gevşek çıkabilir. Gerekirse `--hole-d` ile ayarlanır. '
      'Altıgen bağlantıların 0,2 mm boşluğu da baskıda denenmeli.')
    w('- 3MF dosyaları Bambu Studio\'da açılarak test EDİLMEDİ (makinede Bambu Studio yok). Dosyalar kaynakla aynı yapıda '
      '(basematerials + üçgen başına p1 + paint_color, Metadata/*.config kopyalandı) ve kendi okuyucumuzla geri okundu. '
      'Stand 3MF\'indeki çoklu tabla yerleşimi Bambu\'nun ızgara aralığı (tabla × 1,2) varsayımına dayanıyor; '
      'Bambu nesneleri farklı tablalara dağıtırsa "Arrange" ile düzeltilebilir.')
    w('- Duvar üstü artık oturma yüzeyinden 49,88 yukarıda (50,00 yerine, −0,12). Gaz düğmesi payı bir katman azaldı.')
    w('- Örgü dokusunun ince pulları (< 0,4) 0,4 nozulda tam çıkmayabilir (kaynak tasarımdan gelen durum).')
    w('- Kolon segmentleri ince-uzun (Ø16 × ~88). A1 tabla hareketli bir yazıcı olduğu için brim ve düşük hız önerilir.')
    w('- Alt kat çakmakları: tablodaki "Çakmak yerinde takılır mı" sütununa bakın. "Hayır" ise kılıf pimden kaldırılıp çakmak takılır.')
    with open(C.rp('output', 'report', 'RAPOR.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(L) + '\n')
    print('RAPOR.md written', len(L), 'lines')


if __name__ == '__main__':
    main()
