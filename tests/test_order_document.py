"""PDF, visualização da OS e abertura do WhatsApp, sem envio de mensagens."""
import os
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import test_workflows as fixtures
import app as module


class OrderDocumentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WorkflowTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.client = self.fixture.client
        self.oid = self.fixture.create()

    def snapshot(self):
        with module.app.app_context():
            db = module.get_db()
            return {name: [tuple(row) for row in db.execute('SELECT * FROM '+name+' ORDER BY rowid')]
                for name in ['clients','vehicles','orders','order_items','inventory','os_stock_applied',
                             'fin_transactions','fin_transaction_items']}

    def test_pdf_download_is_available_to_customer_and_preserves_data(self):
        before = self.snapshot()
        for client in [self.client, module.app.test_client()]:
            response = client.get(f'/os/{self.oid}/pdf')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'application/pdf')
            self.assertTrue(response.data.startswith(b'%PDF-'))
            self.assertGreater(len(response.data), 10000)
            self.assertIn(f'FCAR_OS_{self.oid:06d}_ABC1D23.pdf', response.headers['Content-Disposition'])
            self.assertIn('attachment', response.headers['Content-Disposition'])
            self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.client.get('/os/999999999/pdf').status_code, 404)

    def test_whatsapp_opens_correct_contact_and_https_message_without_changing_data(self):
        before = self.snapshot()
        response = self.client.get(f'/os/{self.oid}/whatsapp',
            base_url='http://localhost', headers={'X-Forwarded-Proto':'https'})
        self.assertEqual(response.status_code, 302)
        target = urlsplit(response.location)
        self.assertEqual((target.scheme,target.netloc,target.path), ('https','wa.me','/5531999991111'))
        message = parse_qs(target.query)['text'][0]
        self.assertIn('Olá, João!', message)
        self.assertIn('R$ 220,00', message)
        self.assertIn('https://localhost/os/'+str(self.oid), message)
        self.assertIn('\n', message)
        self.assertEqual(before, self.snapshot())
        anonymous = module.app.test_client().get(f'/os/{self.oid}/whatsapp')
        self.assertIn('/login', anonymous.location)
        self.assertEqual(self.client.get('/os/999999999/whatsapp').status_code,404)

    def test_phone_formats_missing_phone_and_optional_public_origin(self):
        for original, expected in [
            ('(31) 3333-4444','553133334444'), ('31 99999-1111','5531999991111'),
            ('5531999991111','5531999991111'), ('(55) 99999-1234','5555999991234'),
            ('+1 202 555 0100','12025550100'), ('sem telefone',''), ('123','')]:
            with self.subTest(phone=original):
                self.assertEqual(module._os_whatsapp_phone(original),expected)
        with module.app.app_context():
            db = module.get_db()
            db.execute('UPDATE clients SET phone=NULL WHERE id=?',(self.fixture.cid,))
            db.commit()
        with patch.dict(os.environ,{'FCAR_PUBLIC_URL':'https://oficina.exemplo.test'}):
            response = self.client.get(f'/os/{self.oid}/whatsapp')
        self.assertEqual(urlsplit(response.location).path,'/')
        self.assertIn('https://oficina.exemplo.test/os/'+str(self.oid),parse_qs(urlsplit(response.location).query)['text'][0])

    def test_document_actions_and_public_view_do_not_expose_contact_or_admin_actions(self):
        response = self.client.get(f'/os/{self.oid}')
        html = response.get_data(as_text=True)
        for text in ['Salvar PDF','Enviar no WhatsApp','Peças e materiais','Mão de obra e serviços','TOTAL DA OS','order-document.css']:
            self.assertIn(text,html)
        self.assertIn('(31) 99999-1111',html)
        public = module.app.test_client().get(f'/os/{self.oid}?print=1').get_data(as_text=True)
        self.assertIn('Salvar PDF',public)
        self.assertNotIn('(31) 99999-1111',public)
        self.assertNotIn('Enviar no WhatsApp',public)
        self.assertNotIn('Editar atendimento',public)

    def test_pdf_handles_many_items_long_observations_and_literal_markup(self):
        with module.app.app_context():
            db=module.get_db()
            db.execute('UPDATE orders SET notes=? WHERE id=?', ('Observação com acentos & <teste>\n'*45,self.oid))
            db.executemany('INSERT INTO order_items(order_id,description,qty,unit_price,total,is_labor) VALUES (?,?,?,?,?,0)',
                [(self.oid,f'Peça {i} - manutenção e revisão <não é HTML> & '+('REF12345'*15),1,10,10) for i in range(100)])
            db.commit()
        response=self.client.get(f'/os/{self.oid}/pdf')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.data.startswith(b'%PDF-'))
        self.assertIn(b'/Type /Pages',response.data)


if __name__=='__main__':
    unittest.main()
