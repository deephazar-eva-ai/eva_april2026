44:4 • Kletzander, Mannelli Mazzoli, Musliu & Van Hentenryck 

problem. This work uses set partitioning (Balas and Padberg 1976) as the master problem and the RCSPP (Irnich and Desaulniers 2005) as the subproblem. Resources are modeled via resource extension functions (REF) (Irnich 2008). Different techniques for dealing with pareto-front calculation can mostly be found as maxima-finding algorithms in a geometrical context (Bentley 1980; W.-M. Chen et al. 2012). Large neighborhood search (Shaw 1998) is an iterative solution method, where in each iteration a part of the solution is destroyed and rebuilt by dedicated destroy and repair operators. 

## **3 Problem Description** 

The investigated Bus Driver Scheduling Problem (BDSP) deals with the assignment of bus drivers to vehicles that already have a predetermined route for one day of operation. The problem specification was introduced by (Kletzander and Musliu 2020). The notation is summarized in Table 2 at the end of the section. 

## **3.1 Problem Input** 

The input of the BDSP consists of three pieces of data: 

- **Positions and Distance Matrix:** A finite set _𝑃_ ⊆ N of _positions_ . A time distance matrix _𝐷_ = ( _𝑑𝑝𝑞_ ) ∈ R≥[(] _[𝑃]_ 0[×] _[𝑃]_[)] where _𝑑𝑝𝑞_ represents the time needed for a driver to go from position _𝑝_ to _𝑞_ when not actively driving a bus. If no transfer is possible, then we set _𝑑𝑝𝑞_ to a big constant _𝑀_ . If _𝑝_ ≠ _𝑞_ , then _𝑑𝑝𝑞_ is called _passive ride time_ . The value _𝑑𝑝𝑝_ represents the time it takes to switch tour at the same position, but is not considered passive ride time. 

- **Start and End Work** : Shifts can start and end at any position. For each position _𝑝_ ∈ _𝑃_ , the two values _startWork𝑝_ and _endWork𝑝_ represent, respectively, the time required to start or end a shift at that position. This is usually used at the depot as time to prepare the parked bus for use, or shut down and check the bus at the end of the day. Travel to the first position or from the last position is not part of the shift, and therefore not considered in this formulation. 

- **Bus Legs** : A set _𝐿_ of _bus legs_ , where each leg _ℓ_ ∈ _𝐿_ is a 5-tuple: 

_ℓ_ = ( _tourℓ, startPosℓ, endPosℓ, startℓ, endℓ_ ) _,_ 

representing the trip of a vehicle from a start position to an end position over a specified time interval: 

- _tourℓ_ ∈ N is the ID of the vehicle 

- _startPosℓ, endPosℓ_ ∈ _𝑃_ are respectively the starting and the ending positions of the leg 

- _startℓ_ ∈ R is the time at which the vehicle departs from position _startPosℓ_ 

- _endℓ_ ∈ R is the time at which the vehicle arrives at position _endPosℓ_ 

Legs with the same tour _𝑡_ do not overlap, which means that the intervals ( _startℓ, endℓ_ ) for _ℓ_ with _tourℓ_ = _𝑡_ are disjoint. 

Table 1. A Bus Tour Example 

|_ℓ_|_tourℓ_|_startℓ_|_endℓ_|_startPosℓ_|_endPosℓ_|
|---|---|---|---|---|---|
|1|1|400|495|0|1|
|2|1|510|555|1|2|
|3|1|560|602|2|1|
|4|1|608|640|1|0|



Note that _𝐿_ is totally ordered by _start_ , using _tour_ as tie-breaker. Let ⪯ be the relation on _𝐿_ defined as follows: For any _ℓ_ 1 _, ℓ_ 2 ∈ _𝐿_ , write _ℓ_ 1 ⪯ _ℓ_ 2 if 

Journal of Artificial Intelligence Research, Vol. 85, Article 44. Publication date: April 2026. 

Integrating Column Generation and Large Neighborhood Search for Bus Driver Scheduling with Complex Break Constraints • 44:5 

- _startℓ_ 1 _< startℓ_ 2, or 

- _startℓ_ 1 = _startℓ_ 2 and _tourℓ_ 1 ≤ _tourℓ_ 2 

**Lemma 1.** _Then_ ⪯ _is an order relation, and_ ( _𝐿,_ ⪯) _is a totally ordered set._ 

Proof. It is immediate to check that this is an order relation (it is essentially the lexicographic order), and that any _ℓ_ 1 _, ℓ_ 2 ∈ _𝐿_ are in relation, so ( _𝐿,_ ⪯) is a totally ordered set. □ 

Henceforth, all time quantities are expressed in minutes unless otherwise noted. Table 1 shows a short example of one particular bus tour. The vehicle starts at time 400 (6:40 AM) at position 0, does multiple bus legs between positions 1 and 2 with waiting times in between and finally returns to position 0. Within the same vehicle’s tour, bus legs do not overlap in time. Moreover, consecutive bus legs are consecutive in space, satisfying _endPos𝑖_ = _startPos𝑖_ +1. A tour change occurs when a driver has an assignment of two consecutive bus legs _𝑖_ and _𝑗_ with _tour𝑖_ ≠ _tour 𝑗_ . 

## **3.2 Solution** 

A solution _𝑆_ to the BDSP is an assignment of drivers to bus legs. Formally, it is represented as a partition of the set _𝐿_ into disjoint subsets, expressed as _𝑆_ = { _𝑠_ 1 _,𝑠_ 2 _, . . . ,𝑠𝑛_ }. Each block _𝑠𝑖_ is called a **shift** . In practical terms, a _shift_ corresponds to the work scheduled to be performed by a driver in one day (Wren 2004). 

For a given shift _𝑠_ , we denote _𝐿𝑠_ ⊆ _𝐿_ as the subset of bus legs assigned to _𝑠_ . While _𝑠_ and _𝐿𝑠_ are mathematically equivalent, we conceptually distinguish them: _𝐿𝑠_ represents only a set of bus legs, whereas _𝑠_ also contains additional details such as breaks, passive ride time, etc. This additional information is uniquely determined by the set of bus legs _𝐿𝑠_ . Thus, the reader may treat _𝑠_ and _𝐿𝑠_ interchangeably, if it is convenient. 

Note that a priori, the number of shifts of a solution | _𝑆_ | is not given. Nevertheless, we may set it as large as necessary to get a feasible solution. An immediate upper bound is | _𝑆_ | ≤| _𝐿_ |. This represents the situation in which each shift is composed of only one leg. Note that, since the set _𝐿_ is totally ordered (Lemma 1), the notion of _consecutive_ bus legs in a shift is well-defined. Moreover, a solution is also totally ordered by the order induced by the bus legs. 

A solution _𝑆_ is feasible if each of its shifts _𝑠_ ∈ _𝑆_ satisfies the following criteria: 

- Changing tour or position between consecutive bus legs _𝑖, 𝑗_ ∈ _𝑠_ requires 

**==> picture [122 x 11] intentionally omitted <==**

This implies that no overlapping bus legs can be assigned to _𝑠_ . 

- The shift _𝑠_ respects all hard constraints regarding work regulations as specified in the next section. 

## **3.3 Constraints** 

This section describes the constraints derived from the Austrian collective agreement (WKO 2019). Figure 1 depicts an example of a shift with three bus legs. We now list all the hard constraints of a shift _𝑠_ . 

_3.3.1 Total Time._ Let _𝑓_ be the first leg and _ℓ_ the last leg of the shift _𝑠_ . 

**==> picture [379 x 25] intentionally omitted <==**

Equation (1) defines the _total time_ of the shift _𝑠_ : It is the span from the start of work until the end of work. Equation (2) sets the upper bound of _𝑇𝑠_ : No driver can work more than fourteen hours. 

Journal of Artificial Intelligence Research, Vol. 85, Article 44. Publication date: April 2026. 

44:6 • Kletzander, Mannelli Mazzoli, Musliu & Van Hentenryck 

**==> picture [232 x 115] intentionally omitted <==**

**----- Start of picture text -----**<br>
Driving time  𝐷𝑠<br>start work passive ride end work<br>ℓ 1 ℓ 2 ℓ 3<br>rest rest<br>? ?<br>Working time  𝑊𝑠<br>Total time  𝑇𝑠<br>**----- End of picture text -----**<br>


Fig. 1. Example shift (Kletzander and Musliu 2020) 

_3.3.2 Driving Time Regulations._ First, define the _length_ of a bus leg _𝑖_ ∈ _𝐿_ as follows: 

**==> picture [367 x 58] intentionally omitted <==**

Equation (4) defines the _driving time 𝐷𝑠_ of a shift _𝑠_ . Equation (5) sets the upper bound of _𝐷𝑠_ to nine hours. The length of a _driving break_ between two consecutive bus legs _𝑖_ and _𝑗_ is defined as 

_length𝑖𝑗_ = _start 𝑗_ − _end𝑖_ (6) 

The driving break can be split into multiple parts, all of which must be completed _before_ the cumulative driving time without a break reaches four hours: 

- One driving break of at least 30 min; 

- Two driving breaks of at least 20 min each; 

- Three driving breaks of at least 15 min each. 

Once the required break time has been accumulated, a new driving block of at most four hours begins. 

_3.3.3 Shift Splits._ We say that a shift _𝑠_ contains a _shift split_ if there exists a pair of consecutive bus legs _𝑖, 𝑗_ ∈ _𝐿_ such that the break between them satisfies 

**==> picture [142 x 12] intentionally omitted <==**

Here, _ride𝑝,𝑞_ = _𝑑𝑝,𝑞_ denotes the time required for a passive ride between position _𝑝_ and _𝑞_ if _𝑝_ ≠ _𝑞_ , whereas _ride𝑝,𝑝_ = 0. Hence, shift splits refer to breaks longer than three hours. These breaks are unpaid and therefore generally poorly regarded by bus drivers. This plays a role in the objective function. 

Denote by _split𝑠_ the number of shift splits in shift _𝑠_ , and by _splitTime𝑠_ the total duration of these shift splits. A shift split counts as a driving break. 

_3.3.4 Rest break._ Let _𝑖, 𝑗_ ∈ _𝐿_ be two consecutive bus legs in a shift. The break between these two legs can be represented as the time interval [ _end𝑖, start 𝑗_ ], and its length as _length𝑖𝑗_ (as already defined in Equation (6)). We denote with _rest𝑖𝑗_ the length of a _rest break_ : 

**==> picture [309 x 31] intentionally omitted <==**

Journal of Artificial Intelligence Research, Vol. 85, Article 44. Publication date: April 2026. 

Integrating Column Generation and Large Neighborhood Search for Bus Driver Scheduling with Complex Break Constraints • 44:7 

Rest breaks may be split into smaller parts. One part must be at least 30 min, and any additional at least 15 min. The first part must occur within the first 6 h of working time. If there is a section of a rest break of at least 15 min which is not located within the first two or last two hours of the shift, this section is considered _unpaid_ (up to a maximum), as shown in Figure 2. We denote by _unpaid𝑠_ the sum of the length of potentially unpaid rest breaks. 

|2 h|2 h|2 h||2 h|
|---|---|---|---|---|
|paid rest|unpaid rest|||paid rest|
|3 h||centred||3 h|
|30 min break|||||



Fig. 2. Rest break positioning (Kletzander and Musliu 2020) 

The maximum amount of unpaid rest is limited, as shown in Figure 2: 

- If a consecutive part of a rest break of at least 30 minutes is located such that it does not intersect the first 3 h of the shift or the last 3 h of the shift, at most 1.5 h of unpaid rest is allowed and therefore we set _upmax𝑠_ = 90; 

- Otherwise, at most one hour of unpaid rest is allowed, and therefore we set _upmax𝑠_ = 60. 

Rest breaks beyond this limit are paid. 

- _3.3.5 Working Time._ 

**==> picture [379 x 26] intentionally omitted <==**

Equation (7) defines the _working time_ of a shift _𝑠_ . Equation (8) sets the upper bound of _𝑊𝑠_ as 10 h. A minimum rest break is required according to the following options: 

- _𝑊𝑠 <_ 6 h: no rest break required; 

- 6 h ≤ _𝑊𝑠_ ≤ 9 h: at least 30-minute break; 

- _𝑊𝑠 >_ 9 h: at least 45-minute break. 

## **3.4 Objective Function** 

Let _𝑆_ be a solution. The objective function to minimize is defined as follows (Kletzander and Musliu 2020): 

**==> picture [337 x 23] intentionally omitted <==**

where, for every shift _𝑠_ ∈ _𝑆_ : 

- _𝑊𝑠_[′][=][ max][{] _[𝑊][𝑠][,]_[ 390][}][, where] _[ 𝑊][𝑠]_[is the working time defined by][ Equation (7)][. This objective ensures that] drivers are paid for at least _𝑊_ min = 6 _._ 5 hours (390 minutes). 

- _𝑇𝑠_ is the total time of the shift as defined in Equation (1). 

- _ride𝑠_ is the sum of passive ride times between consecutive legs. 

- _change𝑠_ is the number of _tour changes_ , i.e., the number of occurrences of consecutive bus legs _𝑖, 𝑗_ ∈ _𝑠_ with _tour𝑖_ ≠ _tour 𝑗_ . 

- _split𝑠_ is the number of shift splits, as defined in Section 3.3.3. 

The weights were determined by previous work (Kletzander and Musliu 2020) based on preferences agreed by different stakeholders at Austrian bus companies and employee scheduling experts. 

Journal of Artificial Intelligence Research, Vol. 85, Article 44. Publication date: April 2026. 

