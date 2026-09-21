"""Rule-pack and change-detection tests. No Excel is required."""
import os
import sqlite3
import tempfile
import unittest

from xl2ai.catalog import DDL
from xl2ai.changes import detect_changes
from xl2ai.core.config import load_config
from xl2ai.core.runs import Run
from xl2ai.rules import run_packs


class TestRules(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); root=self.tmp.name
        pack=os.path.join(root,"pack.toml")
        with open(pack,"w",encoding="utf-8") as f:
            f.write("""[pack]
name="demo"
version="1.0"
[[rule]]
id="no_negative"
sql="SELECT COUNT(*) FROM {{table:source-a/orders}} WHERE amount < 0"
expect="zero"
severity="error"
[[kpi]]
id="total_amount"
sql="SELECT SUM(amount) FROM {{table:source-a/orders}}"
unit="EGP"
""")
        cfgp=os.path.join(root,"xl2ai.toml")
        with open(cfgp,"w",encoding="utf-8") as f:
            f.write(f'[project]\nname="rules"\n[rules]\npacks=["{pack.replace(os.sep,"/")}"]\n')
        self.cfg=load_config(cfgp)
        self.run=Run.create(self.cfg)
        db=self.run.path("extract","source-a.db"); os.makedirs(os.path.dirname(db),exist_ok=True)
        c=sqlite3.connect(db); c.execute("CREATE TABLE orders (_xl_row INTEGER, amount REAL)")
        c.executemany("INSERT INTO orders VALUES (?,?)",[(2,10.0),(3,20.0)]); c.commit(); c.close()
        cat=self.run.path("catalog.db"); c=sqlite3.connect(cat); c.executescript(DDL)
        c.execute("INSERT INTO _sources VALUES (?,?,?,?,?,?,?,?,?)",
                  ("source-a","x","h",1,"t","full","extract/source-a.db",0,None))
        c.execute("INSERT INTO _tables VALUES (?,?,?,?,?,?,?,?,?,?)",
                  ("t1","source-a","Orders","orders","extract/source-a.db",2,1,1,"visible","fp"))
        c.commit(); c.close()
        self.cat=cat

    def tearDown(self): self.tmp.cleanup()

    def test_rule_and_kpi(self):
        run_packs(self.cfg,self.run.id,self.cat)
        c=sqlite3.connect(self.cat)
        rule=c.execute("SELECT status FROM _rule_results WHERE rule_id='no_negative'").fetchone()[0]
        kpi=c.execute("SELECT value,unit FROM _kpi_results WHERE kpi_id='total_amount'").fetchone()
        c.close()
        self.assertEqual(rule,"pass")
        self.assertEqual(kpi,("30.0","EGP"))


class TestChanges(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); root=self.tmp.name
        cfgp=os.path.join(root,"xl2ai.toml")
        with open(cfgp,"w",encoding="utf-8") as f:f.write('[project]\nname="changes"\n')
        self.cfg=load_config(cfgp)
        self.r1=Run.create(self.cfg); self.r2=Run.create(self.cfg)
        self._cat(self.r1,5,"schema-a","rows-a","10")
        self._cat(self.r2,8,"schema-b","rows-b","15")

    def tearDown(self): self.tmp.cleanup()

    def _cat(self,run,rows,schema,rowfp,kpi):
        p=run.path("catalog.db"); c=sqlite3.connect(p); c.executescript(DDL)
        c.execute("INSERT INTO _sources VALUES (?,?,?,?,?,?,?,?,?)",("s","x","hash"+str(rows),1,"t","full","x.db",0,None))
        c.execute("INSERT INTO _tables VALUES (?,?,?,?,?,?,?,?,?,?)",("t","s","Sheet1","data","x.db",rows,1,1,"visible",schema))
        c.execute("INSERT INTO _columns VALUES (?,?,?,?,?,?,?,?,?,?,?)",("t.c1","t",1,"category","Category",1,"A","TEXT","text",rows,0))
        c.execute("INSERT INTO _profile_columns VALUES (?,?,?,?,?,?,?,?,?)",
                  ("t.c1",rows,0,2,"A","B",None,'[["A",3],["B",2]]','["A","B"]'))
        c.execute("INSERT INTO _table_profiles VALUES (?,?,?,?)",("t",rows,rowfp,"ordered_sha256"))
        c.execute("INSERT INTO _kpi_results VALUES (?,?,?,?,?,?,?,?)",("sales","p","1",kpi,"EGP","{}","p","{}"))
        c.commit(); c.close()

    def test_detects_schema_volume_value_and_kpi_changes(self):
        detect_changes(self.cfg,self.r2.id,previous_run_id=self.r1.id)
        c=sqlite3.connect(self.r2.path("catalog.db"))
        kinds={r[0] for r in c.execute("SELECT kind FROM _changes")}
        c.close()
        self.assertTrue({"source","schema","volume","value","kpi"}.issubset(kinds))


if __name__=="__main__":
    unittest.main(verbosity=2)
