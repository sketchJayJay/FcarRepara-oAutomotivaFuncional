"""Regressões de OS, estoque e financeiro. Usa apenas bancos temporários."""
import contextlib
import csv
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
TEST_ROOT = tempfile.TemporaryDirectory(prefix='fcar-tests-')
os.environ['FCAR_DB_PATH'] = str(Path(TEST_ROOT.name) / 'bootstrap.db')
os.environ['SECRET_KEY'] = 'test-only-secret'
import app as module
from flask import template_rendered
from werkzeug.datastructures import MultiDict


@contextlib.contextmanager
def contexts():
    values = []
    def record(sender, template, context, **extra):
        values.append(context)
    template_rendered.connect(record, module.app)
    try:
        yield values
    finally:
        template_rendered.disconnect(record, module.app)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEST_ROOT.name)
        self.addCleanup(self.temp.cleanup)
        module.DB_PATH = str(Path(self.temp.name) / 'oficina.db')
        module.app.config.update(TESTING=True)
        self.client = module.app.test_client()
        with module.app.app_context():
            module.init_db()
            db = module.get_db()
            db.execute('DELETE FROM inventory')
            db.execute('DELETE FROM mechanics')
            self.cid = db.execute("INSERT INTO clients(name,phone) VALUES ('João Cliente de Teste','(31) 99999-1111')").lastrowid
            self.vid = db.execute("INSERT INTO vehicles(client_id,plate,model) VALUES (?,'ABC-1D23','Volkswagen Gol')", (self.cid,)).lastrowid
            self.mid = db.execute("INSERT INTO mechanics(name) VALUES ('Mecânico de teste')").lastrowid
            self.part = db.execute("INSERT INTO inventory(name,sku,stock,min_stock,price,cost_price) VALUES ('Filtro de óleo','FILTRO',10,2,50,20)").lastrowid
            self.service = db.execute("INSERT INTO inventory(name,sku,stock,min_stock,price,is_labor) VALUES ('Alinhamento','SERV',0,0,80,1)").lastrowid
            db.execute("INSERT INTO inventory(name,stock,min_stock,price) VALUES ('Peça para repor',1,2,10)")
            db.commit()
        with self.client.session_transaction() as session:
            session.update(user_id=1, username='admin')

    def query(self, sql, params=(), all=False):
        with module.app.app_context():
            cursor = module.get_db().execute(sql, params)
            return cursor.fetchall() if all else cursor.fetchone()

    def payload(self, **changes):
        values = dict(client_id=str(self.cid), vehicle_id=str(self.vid), vehicle_plate='ABC-1D23',
            vehicle_text='Volkswagen Gol', mechanic_id=str(self.mid), os_date='2026-01-15',
            status='Aberta', pay_status='Pendente', pay_method='Pix', labor='40', notes='Conferir filtros.',
            item_desc_1='Filtro de óleo', item_inv_1=str(self.part), item_qty_1='2', item_price_1='50', item_is_labor_1='0',
            item_desc_2='Alinhamento', item_inv_2=str(self.service), item_qty_2='1', item_price_2='80', item_is_labor_2='1')
        values.update(changes)
        return values

    def create(self, **changes):
        response = self.client.post('/os/nova', data=self.payload(**changes))
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[-500:])
        return self.query('SELECT MAX(id) FROM orders')[0]

    def test_admin_routes_and_apis_require_login(self):
        anonymous = module.app.test_client()
        for path in ['/', '/os', '/os/nova', '/clientes', '/estoque', '/financeiro', '/api/clients_search', '/api/inventory_search', '/export/backup.sql']:
            with self.subTest(path=path):
                response = anonymous.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertIn('/login', response.location)
        response = anonymous.post('/login?next=https://example.invalid', data={'username':'admin','password':'1234'})
        self.assertEqual(response.location, '/')

    def test_close_repeat_reopen_delete_reconciles_stock_and_finance(self):
        oid = self.create()
        tx = self.query("SELECT * FROM fin_transactions WHERE ref_type='OS' AND ref_id=?", (oid,))
        self.assertEqual((tx['amount'],tx['status'],tx['date']), (220,'PENDENTE','2026-01-15'))
        closed = self.payload(status='Fechada', pay_status='Efetivado', os_date='2026-01-17')
        for _ in range(2):
            self.assertEqual(self.client.post(f'/os/{oid}/editar',data=closed).status_code,302)
            self.assertEqual(self.query('SELECT stock FROM inventory WHERE id=?',(self.part,))[0],8)
        self.assertEqual(self.query("SELECT COUNT(*) FROM fin_transactions WHERE ref_id=? AND ref_type='OS'",(oid,))[0],1)
        tx = self.query('SELECT * FROM fin_transactions WHERE id=?',(tx['id'],))
        self.assertEqual((tx['amount'],tx['status'],tx['date']),(220,'EFETIVADO','2026-01-17'))
        self.client.post(f'/os/{oid}/editar',data=self.payload())
        self.assertEqual(self.query('SELECT stock FROM inventory WHERE id=?',(self.part,))[0],10)
        self.client.post(f'/os/{oid}/editar',data=closed)
        self.client.post(f'/os/{oid}/excluir',data={'next':'https://example.invalid'})
        self.assertEqual(self.query('SELECT stock FROM inventory WHERE id=?',(self.part,))[0],10)
        self.assertIsNone(self.query('SELECT * FROM orders WHERE id=?',(oid,)))
        self.assertEqual(self.query('SELECT status FROM fin_transactions WHERE id=?',(tx['id'],))[0],'CANCELADO')
        self.assertEqual(self.query("SELECT COUNT(*) FROM fin_transaction_items WHERE tx_id=? AND flow='stock'",(tx['id'],))[0],0)
        self.assertEqual(self.query('SELECT stock FROM inventory WHERE id=?',(self.service,))[0],0)

    def test_shortage_rolls_back_vehicle_items_order_and_finance(self):
        oid = self.create()
        response = self.client.post(f'/os/{oid}/editar',data=self.payload(status='Fechada',vehicle_plate='XYZ9A99',item_qty_1='99',os_date='2026-02-01'))
        self.assertEqual(response.status_code,400)
        self.assertIn('Estoque insuficiente',response.get_data(as_text=True))
        self.assertEqual(self.query('SELECT plate FROM vehicles WHERE id=?',(self.vid,))[0],'ABC-1D23')
        self.assertEqual(self.query('SELECT status FROM orders WHERE id=?',(oid,))[0],'Aberta')
        self.assertEqual(self.query('SELECT qty FROM order_items WHERE order_id=? AND inventory_id=?',(oid,self.part))[0],2)
        self.assertEqual(self.query("SELECT date FROM fin_transactions WHERE ref_type='OS' AND ref_id=?",(oid,))[0],'2026-01-15')
        self.assertEqual(self.query('SELECT stock FROM inventory WHERE id=?',(self.part,))[0],10)
        self.assertIn('99',response.get_data(as_text=True))

    def test_finance_failure_never_saves_partial_order(self):
        oid = self.create()
        with patch.object(module,'sync_os_to_finance',side_effect=sqlite3.OperationalError('simulated failure')):
            with self.assertLogs(module.app.logger,level='ERROR'):
                response = self.client.post(f'/os/{oid}/editar',data=self.payload(status='Fechada',vehicle_plate='XYZ9A99'))
        self.assertEqual(response.status_code,503)
        self.assertEqual(self.query('SELECT stock FROM inventory WHERE id=?',(self.part,))[0],10)
        self.assertEqual(self.query('SELECT status FROM orders WHERE id=?',(oid,))[0],'Aberta')
        self.assertEqual(self.query('SELECT plate FROM vehicles WHERE id=?',(self.vid,))[0],'ABC-1D23')
        self.assertEqual(self.query('SELECT COUNT(*) FROM order_items WHERE order_id=?',(oid,))[0],2)

    def test_new_payment_method_does_not_commit_before_finance_finishes(self):
        oid = self.create()
        with patch.object(module,'_rebuild_fin_tx_items',side_effect=sqlite3.OperationalError('simulated detail failure')):
            with self.assertLogs(module.app.logger,level='ERROR'):
                response=self.client.post(f'/os/{oid}/editar',data=self.payload(status='Fechada',pay_method='Forma nova de teste'))
        self.assertEqual(response.status_code,503)
        self.assertEqual(self.query('SELECT stock FROM inventory WHERE id=?',(self.part,))[0],10)
        self.assertEqual(self.query('SELECT status FROM orders WHERE id=?',(oid,))[0],'Aberta')
        self.assertIsNone(self.query("SELECT id FROM fin_payment_methods WHERE name='Forma nova de teste'"))

    def test_service_type_api_validation_and_duplicate_sku(self):
        data = MultiDict([('name','Serviço novo'),('sku','NOVO'),('price','120'),('is_labor','0'),('is_labor','1')])
        self.assertEqual(self.client.post('/estoque',data=data).status_code,302)
        self.assertEqual(self.query("SELECT is_labor FROM inventory WHERE sku='NOVO'")[0],1)
        response = self.client.get('/api/inventory_search?q=servico&limit=bad')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json[0]['is_labor'],1)
        self.assertEqual(self.client.post('/estoque',data=data).status_code,400)
        self.assertEqual(self.client.post('/estoque',data={'name':'Inválido','stock':'-1'}).status_code,400)
        for key,value in [('item_qty_1','-1'),('item_price_1','NaN'),('labor','inf'),('os_date','bad')]:
            with self.subTest(key=key):
                self.assertEqual(self.client.post('/os/nova',data=self.payload(**{key:value})).status_code,400)
        self.assertEqual(self.query('SELECT COUNT(*) FROM orders')[0],0)
        oid = self.create(item_is_labor_2='0',status='Fechada')
        self.assertEqual(self.query('SELECT is_labor FROM order_items WHERE order_id=? AND inventory_id=?',(oid,self.service))[0],1)

    def test_search_pagination_dashboard_counts_and_service_alerts(self):
        with module.app.app_context():
            db=module.get_db()
            db.executemany("INSERT INTO orders(client_id,created_at,os_date,status) VALUES (?,'2026-01-15 12:00:00','2026-01-15','Em andamento')",[(self.cid,)]*35)
            db.commit()
        with contexts() as rendered:
            self.assertEqual(self.client.get('/').status_code,200)
        self.assertEqual(rendered[-1]['stats']['open_os'],35)
        self.assertEqual(len(rendered[-1]['open_os']),6)
        self.assertEqual(rendered[-1]['stats']['low_stock'],1)
        with contexts() as rendered:
            self.client.get('/os?q=joao&status=Em+aberto&page=2')
        self.assertEqual(rendered[-1]['summary']['count'],35)
        self.assertEqual(len(rendered[-1]['rows']),10)
        self.assertTrue(self.client.get('/api/clients_search?q=31999991111').json)
        with contexts() as rendered:
            self.client.get('/clientes?q=ABC1D23')
        self.assertEqual(rendered[-1]['pagination']['count'],1)

    def test_more_than_twenty_items_survive_edit(self):
        data=self.payload()
        for key in list(data):
            if key.startswith('item_'): del data[key]
        for i in range(1,31):
            data.update({f'item_desc_{i}':f'Serviço {i}',f'item_qty_{i}':'1',f'item_price_{i}':'10',f'item_is_labor_{i}':'1'})
        response=self.client.post('/os/nova',data=data)
        self.assertEqual(response.status_code,302)
        oid=self.query('SELECT MAX(id) FROM orders')[0]
        with contexts() as rendered:
            self.client.get(f'/os/{oid}/editar')
        self.assertEqual(len(rendered[-1]['items']),30)
        data['item_price_30']='25'
        self.assertEqual(self.client.post(f'/os/{oid}/editar',data=data).status_code,302)
        self.assertEqual(self.query('SELECT COUNT(*) FROM order_items WHERE order_id=?',(oid,))[0],30)
        self.assertEqual(self.query("SELECT amount FROM fin_transactions WHERE ref_type='OS' AND ref_id=?",(oid,))[0],355)

    def test_exports_dates_and_repasse_use_only_labor(self):
        oid=self.create(status='Fechada',pay_status='Efetivado')
        query='q=joao&start=2026-01-15&end=2026-01-15&pay_status=Efetivado'
        response=self.client.get('/export/os.csv?'+query)
        rows=list(csv.reader(io.StringIO(response.get_data().decode('utf-8-sig')),delimiter=';'))
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[1][7:10],['120.0','100.0','220.0'])
        with contexts() as rendered:
            self.assertEqual(self.client.get('/print/os?'+query).status_code,200)
        self.assertEqual(rendered[-1]['rows'][0]['os_date'],'2026-01-15')
        with contexts() as rendered:
            self.client.get('/relatorio/mecanicos?start=2026-01-15&end=2026-01-15&repasse=50')
        mechanic=next(row for row in rendered[-1]['rows'] if row['mech_id']==self.mid)
        self.assertEqual(mechanic['repasse_valor'],60)
        self.assertEqual(len(rendered[-1]['os_rows']),1)
        self.assertEqual(self.client.get('/export/os_itens.csv?'+query).status_code,200)

    def test_existing_pages_render_and_public_os_still_prints(self):
        oid=self.create()
        paths=['/','/os','/os?page=oops','/clientes','/estoque','/mecanicos','/agenda','/financeiro',
            '/financeiro/lancamentos','/financeiro/estoque','/financeiro/compras','/financeiro/compras/nova',
            '/financeiro/servico_avulso','/relatorio/mecanicos','/acesso',f'/veiculos/{self.cid}',
            f'/clientes/{self.cid}',f'/estoque/{self.part}/editar',f'/os/{oid}/editar',f'/os/{oid}',
            f'/api/clients/{self.cid}/vehicles','/export/backup.sql']
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code,200)
        anonymous=module.app.test_client()
        response=anonymous.get(f'/os/{oid}?print=1')
        self.assertEqual(response.status_code,200)
        self.assertNotIn('Menu principal',response.get_data(as_text=True))
        self.assertEqual(anonymous.get(f'/os/{oid}/qr').mimetype,'image/png')


class StartupTests(unittest.TestCase):
    def launch(self, folder, variable, target):
        binary = folder / 'bin'
        binary.mkdir(exist_ok=True)
        executable = binary / 'gunicorn'
        executable.write_text('#!/bin/sh\nexit 0\n')
        executable.chmod(0o755)
        env = os.environ.copy()
        env.pop('FCAR_DB_PATH', None)
        env.pop('DB_PATH', None)
        env[variable] = str(target)
        env['FORCE_SEED'] = '1'
        env['PATH'] = str(binary) + os.pathsep + str(Path(sys.executable).parent) + os.pathsep + env['PATH']
        result = subprocess.run(['bash', str(Path(__file__).resolve().parents[1] / 'start.sh')],
            cwd=folder, env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_both_database_variables_seed_once_and_keep_existing_volume(self):
        for variable in ['FCAR_DB_PATH', 'DB_PATH']:
            with self.subTest(variable=variable), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                source = sqlite3.connect(folder / 'oficina.db')
                self.addCleanup(source.close)
                source.execute('PRAGMA journal_mode=WAL')
                source.execute('CREATE TABLE marker(value INTEGER)')
                source.execute('INSERT INTO marker VALUES (42)')
                source.commit()
                target = folder / 'volume' / 'oficina.db'
                self.launch(folder, variable, target)
                with sqlite3.connect(target) as check:
                    self.assertEqual(check.execute('SELECT value FROM marker').fetchone()[0], 42)
                    check.execute('UPDATE marker SET value=99')
                self.launch(folder, variable, target)
                with sqlite3.connect(target) as check:
                    self.assertEqual(check.execute('SELECT value FROM marker').fetchone()[0], 99)
                source.close()


if __name__=='__main__':
    unittest.main()
