import copy

from ...src.pipeline.fragments.DisjunctionPipeLine import DisjunctionPipeLine
from ...src.pipeline.fragments.NepPipeLine import NepPipeLine
from .abstract.generic_pipeline import GenericPipeLine
from ..core.elapsed_time import create_zero_time_profile
from ..util.constants import FROM_CLAUSE, START, DONE, RUNNING, PROJECTION, \
    GROUP_BY, AGGREGATE, ORDER_BY, LIMIT, UNION
from ...src.core.aggregation import Aggregation
from ...src.core.from_clause import FromClause
from ...src.core.groupby_clause import GroupBy
from ...src.core.limit import Limit
from ...src.core.orderby_clause import OrderBy
from ...src.core.projection import Projection

class IOState:
    def __init__(self, inp, output):
        self.input = inp
        self.output = output
        self.dic = {
            "input": self.input,
            "output": self.output
        }
    
    def get_dic(self):
        return self.dic


class ExtractionPipeLine(DisjunctionPipeLine,
                         NepPipeLine):

    def __init__(self, connectionHelper, name="Extraction PipeLine"):
        DisjunctionPipeLine.__init__(self, connectionHelper, name)
        NepPipeLine.__init__(self, connectionHelper)
        self.pj = None
        self.global_pk_dict = None

    def process(self, query: str):
        return GenericPipeLine.process(self, query)

    def doJob(self, query, qe=None):
        return GenericPipeLine.doJob(self, query, qe)

    def verify_correctness(self, query, result):
        GenericPipeLine.verify_correctness(self, query, result)

    def extract(self, query):
        self.connectionHelper.connectUsingParams()
        self.info[UNION] = "SKIPPED"
        '''
        From Clause Extraction
        '''
        self.update_state(FROM_CLAUSE + START)
        fc = FromClause(self.connectionHelper)
        self.update_state(FROM_CLAUSE + RUNNING)
        check = fc.doJob(query)
        self.update_state(FROM_CLAUSE + DONE)
        self.time_profile.update_for_from_clause(fc.local_elapsed_time, fc.app_calls)
        io = IOState(query, fc.core_relations)
        if not check or not fc.done:
            self.logger.error("Some problem while extracting from clause. Aborting!")
            self.info[FROM_CLAUSE] = None
            io.output = ""
            return None, self.time_profile
        self.info[FROM_CLAUSE] = fc.core_relations
        self.IO[FROM_CLAUSE] = io.get_dic()
        self.core_relations = fc.core_relations
        self.all_sizes = fc.init.all_sizes
        self.key_lists = fc.get_key_lists()
        self.global_pk_dict = fc.init.global_pk_dict

        eq = self._after_from_clause_extract(query, self.core_relations)
        self.update_state(DONE)
        self.connectionHelper.closeConnection()
        # self.time_profile.update(t)
        return eq

    def _after_from_clause_extract(self, query, core_relations):

        time_profile = create_zero_time_profile()

        check, time_profile = self._mutation_pipeline(core_relations, query, time_profile)
        if not check:
            self.logger.error("Some problem in Regular mutation pipeline. Aborting extraction!")
            self.time_profile.update(time_profile)
            return None

        check, time_profile = self._extract_disjunction(self.aoa.filter_predicates,
                                                        core_relations, query, time_profile)
        if not check:
            self.logger.error("Some problem in disjunction pipeline. Aborting extraction!")
            self.time_profile.update(time_profile)
            return None

        self.time_profile.update(time_profile)
        self.aoa.post_process_for_generation_pipeline(query)
        self.genPipelineCtx = copy.copy(self.aoa.nextPipelineCtx)

        '''
        Projection Extraction
        '''
        self.update_state(PROJECTION + START)
        self.pj = Projection(self.connectionHelper, self.genPipelineCtx)

        self.update_state(PROJECTION + RUNNING)
        check = self.pj.doJob(query)
        self.update_state(PROJECTION + DONE)
        self.time_profile.update_for_projection(self.pj.local_elapsed_time, self.pj.app_calls)
        self.info[PROJECTION] = {'names': self.pj.projection_names, 'attribs': self.pj.projected_attribs}
        if not check:
            self.info[PROJECTION] = None
            self.logger.error("Cannot find projected attributes. ")
            return None, time_profile
        if not self.pj.done:
            self.info[PROJECTION] = None
            self.logger.error("Some error while projection extraction. Aborting extraction!")
            return None, time_profile

        self.update_state(GROUP_BY + START)
        gb = GroupBy(self.connectionHelper, self.genPipelineCtx, self.pj.projected_attribs)
        self.update_state(GROUP_BY + RUNNING)
        check = gb.doJob(query)

        self.update_state(GROUP_BY + DONE)
        self.time_profile.update_for_group_by(gb.local_elapsed_time, gb.app_calls)
        self.info[GROUP_BY] = gb.group_by_attrib
        if not check:
            self.info[GROUP_BY] = None
            self.logger.info("Cannot find group by attributes. ")

        if not gb.done:
            self.info[GROUP_BY] = None
            self.logger.error("Some error while group by extraction. Aborting extraction!")
            return None, time_profile

        for elt in self.aoa.filter_predicates:
            if elt[1] not in gb.group_by_attrib and elt[1] in self.pj.projected_attribs and (
                    elt[2] == '=' or elt[2] == 'equal'):
                gb.group_by_attrib.append(elt[1])

        self.update_state(AGGREGATE + START)
        agg = Aggregation(self.connectionHelper, self.pj.projected_attribs, gb.has_groupby, gb.group_by_attrib,
                          self.pj.dependencies, self.pj.solution, self.pj.param_list, self.genPipelineCtx)
        self.update_state(AGGREGATE + RUNNING)
        check = agg.doJob(query)

        self.update_state(AGGREGATE + DONE)
        self.time_profile.update_for_aggregate(agg.local_elapsed_time, agg.app_calls)
        self.info[AGGREGATE] = agg.global_aggregated_attributes
        if not check:
            self.info[AGGREGATE] = None
            self.logger.info("Cannot find aggregations.")
        if not agg.done:
            self.info[AGGREGATE] = None
            self.logger.error("Some error while extrating aggregations. Aborting extraction!")
            return None, time_profile

        self.update_state(ORDER_BY + START)
        ob = OrderBy(self.connectionHelper, self.pj.projected_attribs, self.pj.projection_names, self.pj.dependencies,
                     agg.global_aggregated_attributes, self.genPipelineCtx)
        self.update_state(ORDER_BY + RUNNING)
        ob.doJob(query)

        self.update_state(ORDER_BY + DONE)
        self.time_profile.update_for_order_by(ob.local_elapsed_time, ob.app_calls)
        self.info[ORDER_BY] = ob.orderBy_string
        if not ob.has_orderBy:
            self.info[ORDER_BY] = None
            self.logger.info("Cannot find aggregations.")
        if not ob.done:
            self.info[ORDER_BY] = None
            self.logger.error("Some error while extrating aggregations. Aborting extraction!")
            return None, time_profile

        self.update_state(LIMIT + START)
        lm = Limit(self.connectionHelper, gb.group_by_attrib, self.genPipelineCtx)
        self.update_state(LIMIT + RUNNING)
        lm.doJob(query)
        self.update_state(LIMIT + DONE)
        self.time_profile.update_for_limit(lm.local_elapsed_time, lm.app_calls)
        self.info[LIMIT] = lm.limit
        if lm.limit is None:
            self.info[LIMIT] = None
            self.logger.info("Cannot find limit.")
        if not lm.done:
            self.info[LIMIT] = None
            self.logger.error("Some error while extracting limit. Aborting extraction!")
            return None, time_profile

        self.q_generator.get_datatype = self.filter_extractor.get_datatype  # method
        self.q_generator.projection = self.pj
        self.q_generator.from_clause = core_relations
        self.q_generator.equi_join = self.aoa
        self.q_generator.or_predicates = self.or_predicates
        self.q_generator.where_clause_remnants = self.genPipelineCtx
        self.q_generator.aggregate = agg
        self.q_generator.orderby = ob
        self.q_generator.limit = lm
        eq = self.q_generator.generate_query_string()
        self.logger.debug("extracted query:\n", eq)

        self.time_profile.update(time_profile)

        eq = self._extract_NEP(core_relations, self.all_sizes, query, self.genPipelineCtx)

        self.time_profile.update_for_app(lm.app.method_call_count)
        return eq
