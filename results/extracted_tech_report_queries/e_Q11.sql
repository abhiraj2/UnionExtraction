Select ps_comment, Sum(ps_availqty*ps_supplycost) as value
 From nation, partsupp, supplier 
 Where n_nationkey = s_nationkey
 and ps_suppkey = s_suppkey
 and n_name = 'ARGENTINA' 
 Group By ps_comment 
 Order By value desc, ps_comment asc 
 Limit 100;