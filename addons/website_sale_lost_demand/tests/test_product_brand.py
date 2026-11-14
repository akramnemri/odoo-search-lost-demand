"""The brand field (Task 2.4a): stored, editable by a product manager, on the product form."""

from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestProductBrand(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product_manager = new_test_user(
            cls.env, login="ld_product_manager", groups="base.group_user,product.group_product_manager"
        )

    def test_brand_is_stored_and_editable(self):
        template = (
            self.env["product.template"]
            .with_user(self.product_manager)
            .create({"name": "Trail running shoe", "brand": "Acme Outdoor"})
        )
        self.assertEqual(template.brand, "Acme Outdoor")
        template.write({"brand": "Acme"})
        self.assertEqual(template.read(["brand"])[0]["brand"], "Acme")
        self.assertEqual(self.env["product.template"].search([("brand", "=", "Acme")]), template)

    def test_brand_is_on_the_product_form(self):
        arch = self.env["product.template"].get_views([(False, "form")])["views"]["form"]["arch"]
        self.assertIn('name="brand"', arch)
