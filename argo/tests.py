from django.test import TransactionTestCase
from argo.models import InstrumentGroup, Instrument, AssetClass
from argo.schemas import InstrumentsSchema, InstrumentSchema
from argo.instruments.search import InteractiveBrokersSearchService, ASSET_CLASS_TO_SEC_TYPE
        

class InstrumentsSchemaLiveTest(TransactionTestCase):
    """
    Live integration test for InstrumentsSchema using the real IB Gateway/TWS service.
    """

    def setUp(self):
        self.group = InstrumentGroup.objects.create(
            name="US Equities Test",
            code="US_TEST",
            symbols=["BTC/USD"],
        )
    def test_search(self):
        matches = InteractiveBrokersSearchService().search(query="BTC/USD")

        assert matches, "Expected to find at least one match for BTC/USD"
        match = next((m for m in matches if m.symbol == "BTC/USD"), None)
        assert match is not None, "Expected to find BTC/USD in the search results"

    def test_sync_model_live_search(self):
        # 1 valid real symbol and 1 non-existent symbol
        schema = InstrumentsSchema(
            instruments=[
                InstrumentSchema(symbol="BTC/USD"),
                InstrumentSchema(symbol="NONEXISTENT_XYZ_999", venue="SMART", currency="USD"),
            ]
        )

        report = schema.sync_model(self.group)

        # Verify report structure
        self.assertIn("created", report)
        self.assertIn("skipped", report)

        created_symbols = [r["name"] for r in report["created"]]
        skipped_symbols = [s["symbol"] for s in report["skipped"]]

        self.assertIn("BTC/USD", created_symbols)
        self.assertIn("NONEXISTENT_XYZ_999", skipped_symbols)

        # Verify database state
        instrument = Instrument.objects.filter(symbol="BTC/USD", venue="SMART").first()
        self.assertIsNotNone(instrument)
        self.assertEqual(instrument.currency, "USD")
        self.assertTrue(hasattr(instrument, "ib_contract"))
        self.assertIn(self.group, instrument.groups.all())
