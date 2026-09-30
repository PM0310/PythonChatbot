import unittest
from unittest.mock import patch
import SalesOrderbot

class TestSalesOrderbot(unittest.TestCase):
    def test_text_chat_sends_payload_and_exits(self):
        responses = [
            "PO1234", "1001", "5", "10", "12",
            "", "", "",  # ship_to_org, sold_to_org, operating_unit default
            "exit",
        ]
        with patch("builtins.input", side_effect=responses), patch(
            "SalesOrderbot.send_order", return_value={"result": "ok"}
        ) as mock_send_order:
            SalesOrderbot.text_chat()

        mock_send_order.assert_called_once()
        sent_payload = mock_send_order.call_args[0][0]
        self.assertEqual(sent_payload["PROCESS_ORDER_Input"]["InputParameters"]["P_HEADER_REC"]["CUST_PO_NUMBER"], "PO1234")
        self.assertEqual(sent_payload["PROCESS_ORDER_Input"]["InputParameters"]["P_LINE_TBL"]["P_LINE_TBL_ITEM"]["INVENTORY_ITEM_ID"], 1001)
        self.assertEqual(sent_payload["PROCESS_ORDER_Input"]["InputParameters"]["P_LINE_TBL"]["P_LINE_TBL_ITEM"]["ORDERED_QUANTITY"], 5)
        self.assertEqual(sent_payload["PROCESS_ORDER_Input"]["InputParameters"]["P_LINE_TBL"]["P_LINE_TBL_ITEM"]["UNIT_LIST_PRICE"], 10)
        self.assertEqual(sent_payload["PROCESS_ORDER_Input"]["InputParameters"]["P_LINE_TBL"]["P_LINE_TBL_ITEM"]["UNIT_SELLING_PRICE"], 12)

    def test_text_chat_exit_immediately(self):
        with patch("builtins.input", side_effect=["exit"]), patch("SalesOrderbot.send_order") as mock_send_order:
            SalesOrderbot.text_chat()
        mock_send_order.assert_not_called()

if __name__ == "__main__":
    unittest.main()