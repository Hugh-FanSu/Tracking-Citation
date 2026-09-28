import unittest
from paper_citation_pipeline.language import classify_samples

EN=('This study examines environmental pollution and the effects of climate change on public health. '
    'The research methods and results provide evidence for sustainable development and environmental policy. ')*5
PT=('Este estudo examina a poluição ambiental e os efeitos das mudanças climáticas na saúde pública. '
    'Os resultados da pesquisa mostram a importância das políticas de proteção do meio ambiente e da sociedade. ')*5
FR=('Cette étude examine les conséquences de la pollution sur la santé et la protection de l’environnement. '
    'Les résultats de cette recherche montrent les effets des changements climatiques sur la société. ')*5

class LanguageTests(unittest.TestCase):
    def test_english_body_with_foreign_abstract(self):
        self.assertEqual(classify_samples([(1,PT),(2,EN),(3,EN)])['status'],'english')
    def test_english_abstract_does_not_include_non_english_body(self):
        for text in [PT,FR]:
            self.assertEqual(classify_samples([(1,EN),(2,text),(3,text)])['status'],'non_english')
    def test_short_or_mixed_text_is_not_silently_english(self):
        self.assertEqual(classify_samples([(1,'UNEP 2020')])['status'],'uncertain')
        self.assertEqual(classify_samples([(1,EN),(2,EN),(3,PT)])['status'],'uncertain')
    def test_single_page_and_repeatable(self):
        a=classify_samples([(1,EN)]);self.assertEqual(a['status'],'english')
        self.assertEqual(a,classify_samples([(1,EN)]))
